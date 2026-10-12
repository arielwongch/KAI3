# Vector Store + Reranker

Status: implemented behavior. Source review: 2026-10-13.

Implementation: [VectorStoreReranker.py](../../src/VectorStoreReranker.py) and
[Reranker.py](../../src/Reranker.py).

## Storage and retrieval

`vector_store_reranker` inherits the [vector store](vector_store.md) write,
embedding, capacity, eviction, isolation, and detached snapshot behavior. Storage
remains process-local. It indexes original turns using MiniLM chunk embeddings.
Writing and inspecting memory never load or invoke the reranker.

For a nonempty query against retained records:

1. Rank original turns by their best chunk cosine similarity, with newer turns
   first on ties. Select the first `candidate_k` turns (default 50).
2. Score query/document pairs using the shared, lazily loaded CPU cross-encoder
   `cross-encoder/ms-marco-MiniLM-L6-v2`, pinned to revision
   `233902d25c440f23af6f7d6e94d2946bac0bee0a`. The adapter explicitly requests raw
   logits; scores are not probabilities and are not comparable with cosine scores.
3. Keep the first 128 reranker tokens of the query. Split each complete candidate
   into overlapping document windows with room for the query and pair special
   tokens within 512 tokens. Overlap is 32 tokens (or a quarter of capacity if
   smaller). Recheck decoded token lengths, covering the complete document.
   Score at most 32 pairs per batch and take the maximum window score per turn.
4. Sort by descending reranker score, retaining the vector ordering on ties.
   Apply final retrieval `k`. Return detached, whole original turns.
5. Benchmarks apply the existing whole-record context budget after final k.
   Oversized turns are skipped without replacement from outside that k.

Empty stores and whitespace-only queries return no candidates or model calls.
Live chat retrieves up to five turns and follows the existing standalone vector
chat context behavior. It does not apply the benchmark context-token allowance.

## Controls and integration

```python
memory = MemoryFactory.create_memory_module(
    'vector_store_reranker', candidate_k=50, max_stored_entries=None,
)
entries = memory.retrieve('Where is the deployment?', k=5)
```

`candidate_k` is a positive integer or Python/JSON null for every retained turn.
CLI and UI accept `all` for null. Final benchmark `retrieval_k` is a separate
positive integer or null, defaulting to null. Here final `all` means all turns
in the shortlist; set both counts to all to rerank and consider the entire store.
A final k larger than the shortlist returns only available shortlisted turns.
`max_stored_entries` defaults to unlimited and otherwise evicts the oldest turn.
Counts reject booleans, fractions, zero, and negative values.

The factory also accepts an injected embedder and reranker. Injected rerankers
implement `score(query, list[str]) -> list[float]`; an optional JSON-serializable
`identity` describes them in snapshots. Missing identity is labelled `injected`.

Chat `/get` accepts `candidate_k` and `max_stored_entries` under `memory_options`,
fixed for that conversation. Chat shows both controls before the first message.
Benchmarks expose `--candidate-k`, final k, capacity, and context budget through
CLI, API, and UI. Candidate controls are rejected for other modes. This mode is
standalone and is not a component of delta, epsilon, or zeta.

## Diagnostics and reproducibility

Returned metadata preserves original dialogue provenance and adds `vector_rank`,
`vector_score`, `reranker_score`, final `retrieval_rank`, `retrieval_score`, and
`retrieval_score_type="cross_encoder_logit"`. Original-turn evidence recall
remains available. Inspection shows the candidate limit, model/revision, scoring
policy, and window settings without inference or exposing weights/vectors.

Exports store the reranker identity at run level and in memory snapshots.
Resume checks that identity, including revision and window/scoring policy, plus
the existing configuration hash that includes candidate k. Existing conditions
retain their prior config hashes and resume behavior.

Reranking is included in retrieval latency, with no memory LLM calls or API token
charges. First retrieval downloads weights if uncached; subsequent instances
share the cached model, with inference guarded by a lock. Dependencies require
sentence-transformers 5.x. Larger pools and longer documents increase CPU work.
The English passage model may not improve conversational retrieval; compare
matched benchmark runs before claiming accuracy gains. Query tails beyond 128
reranker tokens are omitted, and maximum-window scoring favors any relevant span.

## Failures and verification

Model download/inference errors and invalid score counts or nonfinite scores
propagate without falling back to cosine ranking. Retrieval does not mutate
stored records. Existing write atomicity remains intact. Chat reports the normal
503 error; benchmark question failures remain visible and resumable.

[Unit and integration tests](../../tests/test_vector_store_reranker.py) mock
models and API calls. [Frontend tests](../../tests/test_frontend_state.js) cover
controls and request settings. The optional
[real-model smoke test](../../tests/smoke_reranker_memory.py) checks paraphrases
and evidence near the end of a long turn, without paid API calls.
