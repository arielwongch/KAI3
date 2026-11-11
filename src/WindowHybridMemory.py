"""Recent dialogue composed with a summary, archived turns, or current facts."""
from collections import deque
from copy import deepcopy
from threading import RLock

from Embeddings import validate_k
from FactStore import FactStore
from MemoryEntry import MemoryEntry
from MemoryModule import MemoryModule
from SlidingWindow import SlidingWindow
from Summarization import Summarization
from VectorStoreReranker import VectorStoreReranker


class WindowHybridMemory(MemoryModule):
    from MemoryContext import WINDOW_PACKING_POLICY as packing_policy
    def __init__(self, long_term, max_items=10):
        if type(max_items) is not int or max_items < 1:
            raise ValueError("max_items must be a positive integer")
        self.window = SlidingWindow(max_items)
        self.long_term = long_term
        self._lock = RLock()

    def _stage(self, entries):
        incoming = [deepcopy(e) for e in entries if e.text.strip()]
        combined = list(self.window.buffer) + incoming
        limit = self.window.buffer.maxlen
        return incoming, combined[:-limit], deque(combined[-limit:], maxlen=limit)

    def write(self, entry):
        with self._lock:
            incoming, evicted, pending = self._stage([entry])
            if not incoming:
                return
            # Child writes prepare their state before committing. The only
            # operation after success is swapping in the already prepared deque.
            if self.write_policy == "every_turn":
                self.long_term.write(incoming[0])
            elif evicted:
                self.long_term.write(evicted[0])
            self.window.buffer = pending
            self.window.evicted_count += len(evicted)

    def _tag(self, entry, tier, component):
        entry = deepcopy(entry)
        entry.metadata.update(memory_tier=tier, memory_component=component)
        return entry

    def iter_context_candidates(self, query, k=None):
        with self._lock:
            from Diagnostics import retrieval_component
            token = retrieval_component.set(self.component)
            try:
                recalled = self.long_term.iter_context_candidates(query, k)
            finally:
                retrieval_component.reset(token)
            return ([self._tag(e, "long_term", self.component) for e in recalled]
                    + [self._tag(e, "recent", "sliding_window") for e in self.window.buffer])

    def retrieve(self, query, k=50):
        validate_k(k)
        with self._lock:
            recalled = self.long_term.retrieve(query, k)
            return ([self._tag(e, "long_term", self.component) for e in recalled]
                    + [self._tag(e, "recent", "sliding_window") for e in self.window.buffer])

    def inspect(self):
        with self._lock:
            archive = self.long_term.inspect()
            recent = self.window.inspect()
            for snapshot, tier, component in ((archive, "long_term", self.component),
                                               (recent, "recent", "sliding_window")):
                for entry in snapshot["entries"]:
                    entry["metadata"].update(memory_tier=tier, memory_component=component)
            return {"config": {"architecture": self.architecture,
                               "max_items": self.window.buffer.maxlen,
                               "write_policy": self.write_policy,
                               "evicted_count": recent['config']['evicted_count'] + archive['config'].get('evicted_count', 0),
                               "long_term": {"module": self.component, **archive["config"]}},
                    "entries": archive["entries"] + recent["entries"]}


class Alpha(WindowHybridMemory):
    architecture = "alpha"
    component = "summarization"
    write_policy = "on_eviction"

    def __init__(self, max_items=10, summary_limit=10000, max_summary_tokens=None, tokenizer=None):
        if type(summary_limit) is not int or summary_limit < 1:
            raise ValueError("summary_limit must be a positive integer")
        super().__init__(Summarization(summary_limit, max_summary_tokens=max_summary_tokens, tokenizer=tokenizer), max_items)

    def write(self, entry):
        self.write_batch([entry])

    def write_batch(self, entries):
        """Summarize only the evicted prefix; retain individual recent turns."""
        with self._lock:
            incoming, evicted, pending = self._stage(entries)
            if not incoming:
                return
            if evicted:
                self.long_term.write(MemoryEntry("\n\n".join(e.text for e in evicted)))
            self.window.buffer = pending
            self.window.evicted_count += len(evicted)


class Beta(WindowHybridMemory):
    architecture = "beta"
    component = "vector_store"
    write_policy = "on_eviction"

    def __init__(self, max_items=10, embedder=None, max_stored_entries=None, candidate_k=50, reranker=None):
        super().__init__(VectorStoreReranker(embedder=embedder, max_stored_entries=max_stored_entries, candidate_k=candidate_k, reranker=reranker), max_items)


class Gamma(WindowHybridMemory):
    architecture = "gamma"
    component = "fact_store"
    write_policy = "every_turn"

    def __init__(self, max_items=10, embedder=None, extractor=None, max_stored_entries=None, fact_history_mode="current", candidate_k=50, reranker=None):
        store = FactStore
        if fact_history_mode == "versioned":
            from TemporalFactStore import TemporalFactStore
            store = TemporalFactStore
        super().__init__(store(embedder=embedder, extractor=extractor, max_stored_entries=max_stored_entries, candidate_k=candidate_k, reranker=reranker), max_items)


class PeriodicWindowMemory(WindowHybridMemory):
    """Update from each k incoming entries, retaining the latest k verbatim."""
    write_policy = 'every_k_entries'

    def __init__(self, long_term, max_items=10):
        super().__init__(long_term, max_items)
        self._pending = []

    def _update(self, entries):
        if self.component == 'summarization':
            self.long_term.write(MemoryEntry('\n\n'.join(e.text for e in entries)))
        else:
            self.long_term.write_batch(entries)

    def write(self, entry):
        if not entry.text.strip() or entry.metadata.get('completed') is False:
            return
        with self._lock:
            incoming, evicted, window = self._stage([entry])
            pending = self._pending + incoming
            if len(pending) == self.window.buffer.maxlen:
                self._update(pending)
                pending = []
            self.window.buffer, self._pending = window, pending
            self.window.evicted_count += len(evicted)

    def flush(self):
        with self._lock:
            if self._pending:
                self._update(self._pending)
                self._pending = []

    def inspect(self):
        with self._lock:
            snapshot = super().inspect()
            snapshot['config'].update(update_interval=self.window.buffer.maxlen,
                                      pending_entries=len(self._pending),
                                      flush_policy='before_benchmark_qa')
            return snapshot


class WindowedSummarization(PeriodicWindowMemory):
    architecture = 'windowed_summarization'
    component = 'summarization'

    def __init__(self, max_items=10, summary_limit=10000, max_summary_tokens=None, tokenizer=None):
        super().__init__(Summarization(summary_limit, max_summary_tokens=max_summary_tokens,
                                      tokenizer=tokenizer), max_items)


class WindowedFactStore(PeriodicWindowMemory):
    architecture = 'windowed_fact_store'
    component = 'fact_store'

    def __init__(self, max_items=10, embedder=None, extractor=None, max_stored_entries=None,
                 fact_history_mode='current', candidate_k=50, reranker=None):
        store = FactStore
        if fact_history_mode == 'versioned':
            from TemporalFactStore import TemporalFactStore
            store = TemporalFactStore
        super().__init__(store(embedder=embedder, extractor=extractor,
                               max_stored_entries=max_stored_entries, candidate_k=candidate_k,
                               reranker=reranker), max_items)
