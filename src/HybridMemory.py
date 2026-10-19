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
from VectorStore import VectorStore


class HybridMemory(MemoryModule):
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

    def _tag(self, entry, tier, component):
        entry = deepcopy(entry)
        entry.metadata.update(memory_tier=tier, memory_component=component)
        return entry

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
                               "long_term": {"module": self.component, **archive["config"]}},
                    "entries": archive["entries"] + recent["entries"]}


class Alpha(HybridMemory):
    architecture = "alpha"
    component = "summarization"
    write_policy = "on_eviction"

    def __init__(self, max_items=10, summary_limit=10000):
        if type(summary_limit) is not int or summary_limit < 1:
            raise ValueError("summary_limit must be a positive integer")
        super().__init__(Summarization(summary_limit), max_items)

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


class Beta(HybridMemory):
    architecture = "beta"
    component = "vector_store"
    write_policy = "on_eviction"

    def __init__(self, max_items=10, embedder=None):
        super().__init__(VectorStore(embedder=embedder), max_items)


class Gamma(HybridMemory):
    architecture = "gamma"
    component = "fact_store"
    write_policy = "every_turn"

    def __init__(self, max_items=10, embedder=None, extractor=None):
        super().__init__(FactStore(embedder=embedder, extractor=extractor), max_items)
