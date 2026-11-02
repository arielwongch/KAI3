"""Exact vector shortlist followed by cross-encoder reranking of whole turns."""
from Reranker import RerankedMemory
from VectorStore import VectorStore


class VectorStoreReranker(RerankedMemory, VectorStore):
    def __init__(self, embedder=None, reranker=None, max_stored_entries=None, candidate_k=50):
        super().__init__(embedder=embedder, max_stored_entries=max_stored_entries)
        self._configure_reranker(candidate_k, reranker)

    _vector_candidates = VectorStore.iter_context_candidates

    def inspect(self):
        snapshot = super().inspect()
        snapshot['config'].update(self.reranker_config())
        return snapshot
