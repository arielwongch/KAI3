"""Exact vector shortlist followed by cross-encoder reranking of whole turns."""

from copy import deepcopy

from Embeddings import validate_k
from MemoryContext import positive_count
from Reranker import LocalReranker, scores_checked
from VectorStore import VectorStore


class VectorStoreReranker(VectorStore):
    def __init__(self, embedder=None, reranker=None, max_stored_entries=None, candidate_k=50):
        positive_count(candidate_k, 'candidate_k', unlimited=True)
        super().__init__(embedder=embedder, max_stored_entries=max_stored_entries)
        self.candidate_k = candidate_k
        self.reranker = reranker if reranker is not None else LocalReranker()

    def iter_context_candidates(self, query, k=None):
        if k is not None:
            validate_k(k)
        candidates = super().iter_context_candidates(query, self.candidate_k)
        if not candidates:
            return []
        scores = scores_checked(self.reranker.score(query, [entry.text for entry in candidates]), len(candidates))
        # Stable sort retains the cosine ranking (including recency ties).
        ranked = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)
        result = []
        for rank, (entry, score) in enumerate(ranked[:k], 1):
            entry.metadata.update(vector_rank=entry.metadata['retrieval_rank'],
                                  vector_score=entry.metadata['retrieval_score'],
                                  reranker_score=score, retrieval_rank=rank,
                                  retrieval_score=score, retrieval_score_type='cross_encoder_logit')
            result.append(entry)
        return result

    def inspect(self):
        snapshot = super().inspect()
        snapshot['config'].update(candidate_k=self.candidate_k,
                                  reranker=deepcopy(getattr(self.reranker, 'identity', {'model': 'injected'})))
        return snapshot
