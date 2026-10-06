"""Shared, reproducible benchmark token counting and whole-record packing."""
from copy import deepcopy
from functools import lru_cache
import hashlib
from Embeddings import MODEL_NAME, validate_k

TOKENIZER_REVISION = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
PACKING_POLICY = 'whole-record-first-k-greedy-v1'


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


def build_memory_context(module, query, token_budget, tokenizer, retrieval_k=None):
    positive_count(token_budget, 'memory_context_tokens')
    if retrieval_k is not None:
        validate_k(retrieval_k)
    candidates = list(module.iter_context_candidates(query, retrieval_k))
    selected = []
    is_window = getattr(module, 'context_order', None) == 'chronological'

    def ordered(records):
        return list(reversed(records)) if is_window else records

    def render(records):
        return '\n\n'.join(e.text for e in ordered(records))

    for entry in candidates:
        if tokenizer.count(render(selected + [entry])) <= token_budget:
            selected.append(deepcopy(entry))
    text = render(selected)
    entries = ordered(selected)
    return dict(text=text, entries=entries, memory_context_tokens=tokenizer.count(text),
                memory_context_token_budget=token_budget,
                memory_context_bytes=len(text.encode('utf-8')),
                candidate_count=len(candidates), included_count=len(entries),
                omitted_count=len(candidates) - len(entries),
                all_candidates_over_budget=bool(candidates) and not entries,
                context_truncated=getattr(module, 'truncated', False) or any(e.metadata.get('truncated', False) for e in entries),
                retrieval_k=retrieval_k, tokenizer=deepcopy(tokenizer.identity),
                packing_policy=PACKING_POLICY)
