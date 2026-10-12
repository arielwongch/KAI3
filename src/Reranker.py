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
