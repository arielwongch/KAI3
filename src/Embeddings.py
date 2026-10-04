"""Lazy shared local embeddings and exact cosine search utilities."""

from functools import lru_cache
import math
from threading import RLock

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_model_lock = RLock()


@lru_cache(maxsize=1)
def _load_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME, device="cpu")


class LocalEmbeddings:
    def chunks(self, text: str) -> list[str]:
        with _model_lock:
            model = _load_model()
            tokenizer = model.tokenizer
            # This token list is split below, never passed whole to the model.
            tokens = tokenizer.encode(text, add_special_tokens=False, verbose=False)
            limit = model.max_seq_length - tokenizer.num_special_tokens_to_add(pair=False)
            overlap = min(32, limit // 4)
            chunks = []
            start = 0
            while start < len(tokens):
                end = min(start + limit, len(tokens))
                chunk = tokenizer.decode(tokens[start:end], skip_special_tokens=True)
                # Decoding a wordpiece boundary can change its token count.
                while len(tokenizer.encode(chunk, add_special_tokens=True)) > model.max_seq_length:
                    end -= 1
                    chunk = tokenizer.decode(tokens[start:end], skip_special_tokens=True)
                chunks.append(chunk)
                if end == len(tokens):
                    break
                start = max(start + 1, end - overlap)
            return chunks

    def embed(self, texts: list[str]) -> list[list[float]]:
        with _model_lock:
            return _load_model().encode(
                texts, normalize_embeddings=True, show_progress_bar=False,
            ).tolist()


def embed_checked(embedder, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = embedder.embed(texts)
    if len(vectors) != len(texts):
        raise ValueError("Embedding count does not match text count")
    result = []
    dimension = None
    for vector in vectors:
        values = [float(value) for value in vector]
        norm = math.sqrt(sum(value * value for value in values))
        if not values or not math.isfinite(norm) or norm == 0:
            raise ValueError("Embeddings must be finite, nonzero vectors")
        if dimension is not None and len(values) != dimension:
            raise ValueError("Embedding dimensions must match")
        dimension = len(values)
        result.append([value / norm for value in values])
    return result


def similarity(left, right):
    if len(left) != len(right):
        raise ValueError("Embedding dimensions must match")
    return sum(a * b for a, b in zip(left, right))


def validate_k(k):
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")
