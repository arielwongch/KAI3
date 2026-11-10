"""Shared, reproducible benchmark token counting and whole-record packing."""
from copy import deepcopy
from functools import lru_cache
import hashlib
from Embeddings import MODEL_NAME, validate_k

TOKENIZER_REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
PACKING_POLICY = 'whole-record-first-k-greedy-v1'
WINDOW_PACKING_POLICY = 'window-reserved-recall-summary-fit-v3'


class BenchmarkTokenizer:
    def __init__(self):
        from transformers import AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, revision=TOKENIZER_REVISION)
        artifact = self.tokenizer.backend_tokenizer.to_str().encode('utf-8')
        self.identity = dict(id=MODEL_NAME, revision=TOKENIZER_REVISION,
                             artifact_sha256=hashlib.sha256(artifact).hexdigest(),
                             method='fixed-benchmark-wordpiece', exact_provider_tokens=False)

    def count(self, text):
        return len(self.tokenizer.encode(text, add_special_tokens=False, truncation=False,
                                         verbose=False))

    def prefix_offsets(self, text):
        encoding = self.tokenizer(text, add_special_tokens=False, truncation=False,
                                  return_offsets_mapping=True, verbose=False)
        return [end for _, end in encoding['offset_mapping']]


@lru_cache(maxsize=1)
def get_benchmark_tokenizer():
    return BenchmarkTokenizer()


def positive_count(value, name, unlimited=False):
    if unlimited and value is None:
        return
    if type(value) is not int or value < 1:
        raise ValueError(f'{name} must be a positive integer' + (' or null' if unlimited else ''))


def truncate_summary(text, budget, tokenizer):
    if tokenizer.count(text) <= budget:
        return text, False
    marker = '\n[Summary truncated]'
    if tokenizer.count(marker) > budget:
        return '', True
    # Counts are not assumed monotone across arbitrary wordpiece boundaries.
    offsets = tokenizer.prefix_offsets(text)
    for end in reversed([0] + offsets[:budget]):
        candidate = text[:end] + marker
        if tokenizer.count(candidate) <= budget:
            return candidate, True
    return '', True


def fit_summary_entry(entry, token_budget, tokenizer, render, prefix=''):
    """Shorten a detached summary against the complete rendered prompt fragment.

    Labels, separators, and other selected records count toward the allowance.
    Storage truncation remains true even when no additional shortening is needed.
    """
    candidate = deepcopy(entry)
    if tokenizer.count(render(candidate)) <= token_budget:
        return candidate
    original = entry.text[len(prefix):]
    allowance = min(token_budget, tokenizer.count(original))
    while allowance > 0:
        text, truncated = truncate_summary(original, allowance, tokenizer)
        if not text or not text.removesuffix('\n[Summary truncated]').strip():
            return None
        candidate.text = prefix + text
        candidate.metadata['truncated'] = entry.metadata.get('truncated', False) or truncated
        candidate.metadata['context_shortened'] = True
        excess = tokenizer.count(render(candidate)) - token_budget
        if excess <= 0:
            return candidate
        allowance -= max(1, excess)
    return None


def build_memory_context(module, query, token_budget, tokenizer, retrieval_k=None):
    positive_count(token_budget, 'memory_context_tokens')
    if retrieval_k is not None:
        validate_k(retrieval_k)
    from HybridMemory import HybridMemory
    from Compaction import Compaction
    if isinstance(module, Compaction):
        return module.build_context(query, token_budget, tokenizer, retrieval_k)
    if isinstance(module, HybridMemory):
        return module.build_context(query, token_budget, tokenizer, retrieval_k)
    candidates = list(module.iter_context_candidates(query, retrieval_k))
    selected = []
    is_window = getattr(module, 'context_order', None) == 'chronological'
    recent_first = getattr(module, 'packing_policy', None) == WINDOW_PACKING_POLICY
    if recent_first:
        recent = [e for e in candidates if e.metadata.get('memory_tier') == 'recent']
        candidates = list(reversed(recent)) + [e for e in candidates if e.metadata.get('memory_tier') != 'recent']
    recent_order = {id(e): i for i, e in enumerate(recent)} if recent_first else {}

    def ordered(records):
        if recent_first:
            # Spillover can admit a newer turn after an older, smaller one.
            # Restore source order rather than reversing admission order.
            recent_records = [e for e in records if e.metadata.get('memory_tier') == 'recent']
            # Selection uses detached copies, so retain their source positions
            # separately instead of relying on record equality or dialogue IDs.
            recent_records.sort(key=lambda e: recent_order[id(e)])
            return ([e for e in records if e.metadata.get('memory_tier') != 'recent']
                    + recent_records)
        return list(reversed(records)) if is_window else records

    def render(records):
        return format_context(ordered(records))

    def append_entry(entry):
        candidate = deepcopy(entry)
        if recent_first and entry.metadata.get('memory_tier') == 'recent':
            recent_order[id(candidate)] = recent_order[id(entry)]
        selected.append(candidate)

    def admit(entry):
        if entry.metadata.get('type') == 'summary' or entry.metadata.get('memory_component') == 'summarization':
            candidate = fit_summary_entry(entry, token_budget, tokenizer,
                                          lambda e: render(selected + [e]))
            if candidate is not None:
                selected.append(candidate)
                return True
            return False
        if tokenizer.count(render(selected + [entry])) <= token_budget:
            append_entry(entry)
            return True
        return False

    reserved_long_term = 0
    if recent_first:
        long_term = [e for e in candidates if e.metadata.get('memory_tier') != 'recent']
        # Leave up to half the allowance for recall. An empty or small archive
        # releases its unused space to recent turns; all counts include framing.
        if long_term:
            reserved_long_term = min(token_budget // 2, tokenizer.count(render(long_term)))
        deferred = []
        for entry in candidates[:len(recent)]:
            if tokenizer.count(render(selected + [entry])) <= token_budget - reserved_long_term:
                append_entry(entry)
            else:
                deferred.append(entry)
        # Under tiny budgets, prefer at least one complete recent turn when
        # framing makes it impossible to honor both reservations.
        if not selected:
            for index, entry in enumerate(deferred):
                if admit(entry):
                    deferred.pop(index)
                    break
        for entry in long_term:
            admit(entry)
        for entry in deferred:
            admit(entry)
    else:
        for entry in candidates:
            admit(entry)
    text = render(selected)
    entries = ordered(selected)
    from ExperimentRecording import capture
    from Diagnostics import entries_json
    candidate_artifact = capture('context-candidates', dict(
        ordering='packing admission order', entries=entries_json(candidates)))
    result = dict(text=text, entries=entries, memory_context_tokens=tokenizer.count(text),
                candidate_artifact=candidate_artifact,
                memory_context_token_budget=token_budget,
                memory_context_bytes=len(text.encode('utf-8')),
                candidate_count=len(candidates), included_count=len(entries),
                omitted_count=len(candidates) - len(entries),
                all_candidates_over_budget=bool(candidates) and not entries,
                context_truncated=getattr(module, 'truncated', False) or any(e.metadata.get('truncated', False) for e in entries),
                retrieval_k=retrieval_k, tokenizer=deepcopy(tokenizer.identity),
                packing_policy=WINDOW_PACKING_POLICY if recent_first else PACKING_POLICY)
    if recent_first:
        result['tiers'] = {}
        for tier in ('recent', 'long_term'):
            available = [e for e in candidates if e.metadata.get('memory_tier') == tier]
            included = sum(e.metadata.get('memory_tier') == tier for e in entries)
            result['tiers'][tier] = dict(candidate_count=len(available), included_count=included,
                omitted_count=len(available)-included,
                reserved_tokens=reserved_long_term if tier == 'long_term' else token_budget-reserved_long_term,
                shortened_count=sum(e.metadata.get('memory_tier') == tier and
                                    e.metadata.get('context_shortened', False) for e in entries),
                oversized_count=sum(tokenizer.count(format_context([e])) > token_budget for e in available))
        result['long_term_context_omitted'] = bool(result['tiers']['long_term']['candidate_count']
                                                   and not result['tiers']['long_term']['included_count'])
    return result


def retrieval_k(module):
    from SlidingWindow import SlidingWindow
    return module.buffer.maxlen if isinstance(module, SlidingWindow) else 5


def format_context(entries, separator='\n\n'):
    if not any(e.metadata.get('memory_tier') for e in entries):
        return separator.join(e.text for e in entries)
    labels = {'summarization': 'Earlier conversation summary',
              'vector_store': 'Retrieved earlier conversation turns',
              'fact_store': 'Current and historical asserted facts',
              'sliding_window': 'Recent conversation (oldest to newest)'}
    sections = []
    for component, label in labels.items():
        texts = [e.text for e in entries if e.metadata.get('memory_component') == component]
        if texts:
            sections.append(label + ':\n' + separator.join(texts))
    return ('Explicit recent corrections supersede older statements for current-state questions. '
            'For historical questions, use statements applicable to the requested time; '
            'distinguish corrections of errors from changes over time.\n\n'
            + '\n\n'.join(sections))
