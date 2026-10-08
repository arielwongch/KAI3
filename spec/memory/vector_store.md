# Vector memory

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

Implementation: [VectorStore.py](../../src/VectorStore.py) and
[Embeddings.py](../../src/Embeddings.py).

## Purpose

The store indexes original dialogue using semantic embeddings and returns
whole turns whose chunks resemble the question.

## Stored data and write flow

1. Ignore whitespace-only writes; otherwise deep-copy the formatted turn.
2. Tokenize the full text and split it into overlapping chunks. Chunk content
   capacity is the embedding model's sequence limit minus special tokens;
   overlap is `min(32, capacity // 4)` tokens. Recheck decoded chunk lengths so
   each re-encoded chunk fits the model.
3. Embed every chunk using the lazily loaded, shared CPU model
   `sentence-transformers/all-MiniLM-L6-v2`. Validate vector counts, dimensions,
   and finite nonzero norms, then normalize vectors to unit length.
4. Store `(original MemoryEntry, list of chunk vectors)` in an ordered list.
   Prepare embeddings before appending, so embedding failure leaves memory
   unchanged. There is no generative memory LLM call.
5. Storage is unlimited by default. A finite capacity counts original turns,
   not chunks, and removes the oldest turn and all its vectors after overflow.

## Retrieval

Embed the question once and calculate exact cosine similarity
against every stored chunk. A turn's score is:

```text
score(turn, question) = max(cosine(question_vector, chunk_vector))
```

Sort by descending score, breaking ties in favor of later-ingested turns. Return
each original turn once, regardless of how many chunks match. Candidate metadata
includes `retrieval_rank`, `retrieval_score`, and
`retrieval_score_type="cosine_similarity"`, in addition to the original metadata.
Apply k, then shared token packing; preserve ranking in the final context.

## Limitations

There is no minimum similarity threshold, approximate index, keyword
reranker, or automatic neighboring-turn expansion. Empty stores and blank queries
return no candidates. A matching chunk does not allow a long original turn to be
partially supplied: the entire turn must fit. Query embedding uses the model's
normal encoding path rather than dialogue chunking. Original dialogue IDs support
evidence coverage. Inspection shows original entries and chunk counts, not vectors.

## Interfaces and configuration

`MemoryFactory.create_memory_module("vector_store", embedder=None,
max_stored_entries=None)` creates the store. Injected embedders implement
`embed(list[str])` and `chunks(str)`. Capacity is positive or null; benchmark
candidate k is positive or null. Live `retrieve` defaults to k=5 and requires
a positive integer.

The [shared interface](interface.md) defines module calls and snapshots.
The benchmark applies [context packing](../benchmark/context_budget.md) after
candidate selection; storage and retrieval limits are independent.

## Failure behavior

Invalid counts raise `ValueError`. Chunking or embedding failures occur before
append/eviction and preserve existing records. Query embedding failure
propagates rather than falling back to lexical search.

## Verification

[Semantic memory tests](../../tests/test_semantic_memory.py) cover chunking,
ranking, ties, copies, and embedding failures. [Controlled comparison tests](../../tests/test_controlled_comparison.py)
cover finite capacity, more than five candidates, and whole-turn packing.
