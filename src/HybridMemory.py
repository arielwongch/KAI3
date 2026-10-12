"""Independent paired memories with transactional writes and shared context budgets."""
from copy import deepcopy
import math
from threading import RLock
import time

from Diagnostics import collector
from Embeddings import validate_k
from MemoryEntry import MemoryEntry
from MemoryModule import MemoryModule
from MemoryContext import positive_count, truncate_summary

HYBRIDS = {
    'delta': ('summarization', 'vector_store'),
    'epsilon': ('summarization', 'fact_store'),
    'zeta': ('vector_store', 'fact_store'),
}
HYBRID_PACKING_POLICY = 'hybrid-reserved-shares-spillover-v1'


def hybrid_settings(mode, shares=None, component_options=None):
    names = HYBRIDS[mode]
    shares = dict.fromkeys(names, 0.5) if shares is None else shares
    if (not isinstance(shares, dict) or set(shares) != set(names)
            or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v < 1
                   for v in shares.values())
            or not math.isclose(sum(shares.values()), 1, rel_tol=0, abs_tol=1e-9)):
        raise ValueError('hybrid_shares must name both components with positive shares summing to 1')
    options = {} if component_options is None else component_options
    records = set(names) - {'summarization'}
    if not isinstance(options, dict) or set(options) - records:
        raise ValueError('component_options may configure only the hybrid record components')
    for name, values in options.items():
        if not isinstance(values, dict) or set(values) - {'retrieval_k', 'max_stored_entries'}:
            raise ValueError('Component options support retrieval_k and max_stored_entries only')
        for key, value in values.items():
            positive_count(value, key, unlimited=True)
    return {name: float(shares[name]) for name in names}, deepcopy(options)


class HybridMemory(MemoryModule):
    def __init__(self, mode, components, hybrid_shares=None, component_options=None,
                 memory_context_tokens=2000, tokenizer=None):
        self.mode = mode
        self.hybrid_shares, self.component_options = hybrid_settings(mode, hybrid_shares, component_options)
        positive_count(memory_context_tokens, 'memory_context_tokens')
        if tuple(components) != HYBRIDS[mode]:
            raise ValueError('Hybrid components must match the architecture in order')
        self.components = components
        self.memory_context_tokens = memory_context_tokens
        self.tokenizer = tokenizer
        self._lock = RLock()
        self.component_usage = {name: dict(write_seconds=0., memory_llm_calls=0, memory_tokens=0)
                                for name in components}

    def write(self, entry):
        self.write_batch([entry])

    def write_batch(self, entries):
        """Commit all component updates together; billable failed work stays in metrics."""
        entries = list(entries)
        if not entries:
            return
        # Copy logical state, never service objects, model weights, or locks.
        excluded = {'embedder', 'extractor', 'tokenizer', '_lock'}
        with self._lock:
            states = {name: deepcopy({k: v for k, v in vars(component).items() if k not in excluded})
                      for name, component in self.components.items()}
            try:
                for name, component in self.components.items():
                    parent = collector.get()
                    usage = dict(memory_llm_calls=0, memory_tokens=0,
                                 memory_prompt_tokens=0, memory_completion_tokens=0)
                    token = collector.set(usage)
                    started = time.perf_counter()
                    try:
                        if name == 'summarization':
                            component.write(MemoryEntry('\n\n'.join(e.text for e in entries),
                                                        deepcopy(entries[0].metadata)))
                        else:
                            for entry in entries:
                                component.write(deepcopy(entry))
                    finally:
                        collector.reset(token)
                        self.component_usage[name]['write_seconds'] += time.perf_counter() - started
                        for key, value in usage.items():
                            for target in (self.component_usage[name], parent):
                                if target is not None:
                                    previous = target.get(key, 0)
                                    target[key] = None if previous is None or value is None else previous + value
            except BaseException:
                for name, component in self.components.items():
                    for key in list(vars(component)):
                        if key not in excluded:
                            delattr(component, key)
                    vars(component).update(states[name])
                raise

    def inspect(self):
        with self._lock:
            snapshots = {name: component.inspect() for name, component in self.components.items()}
            entries = []
            for name, snapshot in snapshots.items():
                for record in deepcopy(snapshot['entries']):
                    record.setdefault('metadata', {})['component'] = name
                    entries.append(record)
            return dict(config=dict(architecture=self.mode, hybrid_shares=deepcopy(self.hybrid_shares),
                                    component_options=deepcopy(self.component_options),
                                    memory_context_tokens=self.memory_context_tokens,
                                    packing_policy=HYBRID_PACKING_POLICY,
                                    evicted_count=sum(s['config'].get('evicted_count', 0) for s in snapshots.values())),
                        entries=entries, components=snapshots, component_usage=deepcopy(self.component_usage))

    def _candidates(self, query, k):
        if k is not None:
            validate_k(k)
        groups = {}
        for name, component in self.components.items():
            limit = None if name == 'summarization' else self.component_options.get(name, {}).get('retrieval_k', k)
            candidates = list(component.iter_context_candidates(query, limit))
            for entry in candidates:
                entry.metadata['component'] = name
                entry.text = f'[{name}]\n{entry.text}'
            groups[name] = candidates
        return groups

    def iter_context_candidates(self, query, k=None):
        with self._lock:
            return [entry for group in self._candidates(query, k).values() for entry in group]

    def retrieve(self, query, k=5):
        from MemoryContext import get_benchmark_tokenizer
        tokenizer = self.tokenizer or get_benchmark_tokenizer()
        return self.build_context(query, self.memory_context_tokens, tokenizer, k)['entries']

    def build_context(self, query, token_budget, tokenizer, retrieval_k=None):
        positive_count(token_budget, 'memory_context_tokens')
        with self._lock:
            groups = self._candidates(query, retrieval_k)
        names = list(groups)
        first_budget = int(token_budget * self.hybrid_shares[names[0]])
        budgets = dict(zip(names, (first_budget, token_budget - first_budget)))
        selected = {name: [] for name in names}
        pending = []

        def render(records):
            return '\n\n'.join(e.text for e in records)

        def flattened():
            return [entry for name in names for entry in selected[name]]

        # Reserve shares before allowing either component to consume spare space.
        for name, candidates in groups.items():
            for entry in candidates:
                candidate = deepcopy(entry)
                if name == 'summarization' and tokenizer.count(candidate.text) > budgets[name]:
                    candidate.text, truncated = truncate_summary(candidate.text, budgets[name], tokenizer)
                    candidate.metadata['truncated'] = truncated
                    if not candidate.text.startswith('[summarization]\n'):
                        candidate.text = ''
                if (candidate.text and tokenizer.count(render(selected[name] + [candidate])) <= budgets[name]
                        and tokenizer.count(render(flattened() + [candidate])) <= token_budget):
                    selected[name].append(candidate)
                else:
                    pending.append((name, entry))
        # A shortened summary can also borrow spare space. Count the complete
        # rendered context rather than assuming token counts are additive.
        if selected.get('summarization') and groups['summarization']:
            shortened = selected['summarization'][0]
            original = groups['summarization'][0]
            allowance = token_budget
            while allowance > tokenizer.count(shortened.text):
                expanded = deepcopy(original)
                expanded.text, truncated = truncate_summary(original.text, allowance, tokenizer)
                expanded.metadata['truncated'] = original.metadata.get('truncated', False) or truncated
                selected['summarization'][0] = expanded
                excess = tokenizer.count(render(flattened())) - token_budget
                if excess <= 0:
                    break
                selected['summarization'][0] = shortened
                allowance -= max(1, excess)
        # Stable round-robin spillover avoids comparing scores across representations.
        pending.sort(key=lambda item: (item[1].metadata.get('retrieval_rank', 0), names.index(item[0])))
        for name, entry in pending:
            selected[name].append(entry)
            if tokenizer.count(render(flattened())) > token_budget:
                selected[name].pop()
        entries = flattened()
        context = render(entries)
        count = sum(len(group) for group in groups.values())
        return dict(text=context, entries=entries, memory_context_tokens=tokenizer.count(context),
                    memory_context_token_budget=token_budget, memory_context_bytes=len(context.encode('utf-8')),
                    candidate_count=count, included_count=len(entries), omitted_count=count-len(entries),
                    all_candidates_over_budget=bool(count) and not entries,
                    context_truncated=any(e.metadata.get('truncated', False) for e in entries),
                    retrieval_k=retrieval_k, tokenizer=deepcopy(tokenizer.identity),
                    packing_policy=HYBRID_PACKING_POLICY,
                    components={name: dict(share=self.hybrid_shares[name], reserved_tokens=budgets[name],
                                memory_context_tokens=tokenizer.count(render(selected[name])),
                                candidate_count=len(groups[name]), included_count=len(selected[name]),
                                retrieval_k=None if name == 'summarization' else self.component_options.get(name, {}).get('retrieval_k', retrieval_k))
                                for name in names})
