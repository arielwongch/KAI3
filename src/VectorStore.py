from dataclasses import asdict
from Embeddings import MODEL_NAME
from copy import deepcopy
from threading import RLock

from Embeddings import LocalEmbeddings, embed_checked, similarity, validate_k
from MemoryEntry import MemoryEntry
from MemoryModule import MemoryModule


class VectorStore(MemoryModule):
    def __init__(self, embedder=None):
        self.embedder = embedder if embedder is not None else LocalEmbeddings()
        self._records = []
        self._lock = RLock()

    def write(self, entry: MemoryEntry) -> None:
        if not entry.text.strip():
            return
        with self._lock:
            stored = deepcopy(entry)
            chunks = self.embedder.chunks(stored.text)
            if not chunks:
                raise ValueError("Nonempty entries must produce embedding chunks")
            vectors = embed_checked(self.embedder, chunks)
            if self._records:
                similarity(self._records[0][1][0], vectors[0])
            self._records.append((stored, vectors))

    def retrieve(self, query: str, k: int = 5) -> list[MemoryEntry]:
        validate_k(k)
        with self._lock:
            if not self._records or not query.strip():
                return []
            query_vector = embed_checked(self.embedder, [query])[0]
            ranked = sorted(
                enumerate(self._records),
                key=lambda item: (
                    max(similarity(query_vector, vector) for vector in item[1][1]),
                    item[0],
                ),
                reverse=True,
            )
            results = []
            for rank, (_, record) in enumerate(ranked[:k], 1):
                entry = deepcopy(record[0])
                entry.metadata['retrieval_rank'] = rank
                entry.metadata['retrieval_score'] = max(similarity(query_vector, vector) for vector in record[1])
                entry.metadata['retrieval_score_type'] = 'cosine_similarity'
                results.append(entry)
            return results


    def inspect(self):
        with self._lock:
            return {"config": {"embedding_model": MODEL_NAME}, "entries": [dict(asdict(deepcopy(e)), chunk_count=len(v)) for e, v in self._records]}
