"""Pinned, lazy local cross-encoder with whole-document window scoring."""

from functools import lru_cache
import math
from threading import RLock

MODEL_NAME = 'cross-encoder/ms-marco-MiniLM-L6-v2'
MODEL_REVISION = '233902d25c440f23af6f7d6e94d2946bac0bee0a'
MAX_LENGTH = 512
MAX_QUERY_TOKENS = 128
WINDOW_OVERLAP = 32
BATCH_SIZE = 32
POLICY = 'query-prefix-overlapping-windows-max-logit-v1'
_model_lock = RLock()


def reranker_identity():
    return dict(model=MODEL_NAME, revision=MODEL_REVISION, device='cpu',
                max_length=MAX_LENGTH, max_query_tokens=MAX_QUERY_TOKENS,
                window_overlap=WINDOW_OVERLAP, batch_size=BATCH_SIZE,
                policy=POLICY, score_type='cross_encoder_logit')


@lru_cache(maxsize=1)
def _load_model():
    from sentence_transformers import CrossEncoder
    import torch

    return CrossEncoder(MODEL_NAME, revision=MODEL_REVISION, device='cpu',
                        max_length=MAX_LENGTH, activation_fn=torch.nn.Identity())


def scores_checked(scores, count):
    scores = list(scores)
    if len(scores) != count:
        raise ValueError('Reranker score count does not match candidate count')
    values = [float(score) for score in scores]
    if any(not math.isfinite(score) for score in values):
        raise ValueError('Reranker scores must be finite')
    return values


def _decode_fitting(tokenizer, tokens, limit):
    """Decoded wordpiece boundaries can expand when encoded again."""
    end = min(len(tokens), limit)
    while end:
        text = tokenizer.decode(tokens[:end], skip_special_tokens=True)
        if len(tokenizer.encode(text, add_special_tokens=False, verbose=False)) <= limit:
            return text, end
        end -= 1
    raise ValueError('Reranker could not fit a nonempty token window')


def _pairs(tokenizer, query, texts):
    query_tokens = tokenizer.encode(query, add_special_tokens=False, verbose=False)
    query_text = _decode_fitting(tokenizer, query_tokens, MAX_QUERY_TOKENS)[0] if query_tokens else ''
    query_size = len(tokenizer.encode(query_text, add_special_tokens=False, verbose=False))
    capacity = MAX_LENGTH - tokenizer.num_special_tokens_to_add(pair=True) - query_size
    if capacity < 1:
        raise ValueError('Reranker query leaves no room for document text')
    overlap = min(WINDOW_OVERLAP, capacity // 4)
    for index, text in enumerate(texts):
        tokens = tokenizer.encode(text, add_special_tokens=False, verbose=False)
        if not tokens:
            yield index, (query_text, '')
        start = 0
        while start < len(tokens):
            window, consumed = _decode_fitting(tokenizer, tokens[start:start + capacity], capacity)
            yield index, (query_text, window)
            if start + consumed == len(tokens):
                break
            start += max(1, consumed - overlap)


class LocalReranker:
    @property
    def identity(self):
        return reranker_identity()

    def score(self, query, texts):
        if not texts:
            return []
        with _model_lock:
            model = _load_model()
            result = [-math.inf] * len(texts)
            batch = []

            def flush():
                values = scores_checked(model.predict([pair for _, pair in batch],
                                        batch_size=BATCH_SIZE, show_progress_bar=False), len(batch))
                for (index, _), value in zip(batch, values):
                    result[index] = max(result[index], value)
                batch.clear()

            for item in _pairs(model.tokenizer, query, texts):
                batch.append(item)
                if len(batch) == BATCH_SIZE:
                    flush()
            if batch:
                flush()
            return scores_checked(result, len(texts))


class RerankedMemory:
    """Shared shortlist/rerank policy for embedded turns and facts."""
    def _configure_reranker(self, candidate_k, reranker):
        from MemoryContext import positive_count
        positive_count(candidate_k, 'candidate_k', unlimited=True)
        self.candidate_k = candidate_k
        self.reranker = reranker if reranker is not None else LocalReranker()

    def reranker_config(self):
        from copy import deepcopy
        return dict(candidate_k=self.candidate_k,
                    reranker=deepcopy(getattr(self.reranker, 'identity', {'model': 'injected'})))

    def iter_context_candidates(self, query, k=None):
        from Embeddings import validate_k
        if k is not None:
            validate_k(k)
        candidates = self._vector_candidates(query, self.candidate_k)
        from Diagnostics import record_retrieval
        record_retrieval('reranker_pool', candidates, candidate_k=self.candidate_k)
        if not candidates:
            return []
        scores = scores_checked(self.reranker.score(query, [e.text for e in candidates]), len(candidates))
        ranked = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)
        result = []
        for rank, (entry, score) in enumerate(ranked[:k], 1):
            entry.metadata.update(vector_rank=entry.metadata['retrieval_rank'],
                                  vector_score=entry.metadata['retrieval_score'],
                                  reranker_score=score, retrieval_rank=rank,
                                  retrieval_score=score, retrieval_score_type='cross_encoder_logit')
            result.append(entry)
        record_retrieval('reranked_final', result, retrieval_k=k)
        return result
