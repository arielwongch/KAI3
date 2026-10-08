# Current fact memory

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

## Purpose

Live-chat `FactStore` retains current atomic assertions made by the user. It
replaces corrected information and deletes retractions. It is distinct from
[temporal facts](temporal_fact_store.md), which the LoCoMo v3 benchmark selects
to preserve historical versions.

## Interfaces and configuration

```python
memory = MemoryFactory.create_memory_module(
    "fact_store", fact_history_mode="current",
    embedder=None, extractor=None, max_stored_entries=None,
)
```

`current` is the factory default. The extractor defaults to `API.call_api` and
takes `(system_prompt, user_input)`, returning `(text, latency, tokens)`.
The embedder supports `embed(list[str])`; it defaults to local CPU MiniLM.
Capacity is null/unlimited or a positive integer. `retrieve` defaults to k=30,
but the chat agent explicitly requests k=5. Benchmark-style candidates accept
positive k or null. See the [shared interface](interface.md).

## Stored data

An insertion-ordered dictionary maps `fact-N` IDs to an entry, normalized vector,
and last changed revision. Entry text contains one atomic assertion. Metadata
contains `type="fact"`, `fact_id`, a deep copy of the write's metadata in `source`,
and user assertion text in `source_text`. This is creation/update provenance,
not a collection of validated benchmark dialogue support IDs.

There is no historical version table. Replacements keep their fact ID and
dictionary position; the old assertion and embedding are discarded. Finite
capacity removes the earliest-inserted surviving facts and increments
`evicted_count`. Replacing a fact does not refresh eviction order.

## Write and update flow

1. Ignore `completed=False` entries and blank user text. Read `user_text` from
   metadata, falling back to entry text. Assistant text is context only.
2. Send all current fact IDs/texts, user text, and assistant context to the
   extractor. The prompt excludes questions, hypotheticals, and assistant claims
   as assertion evidence.
3. Require JSON with only an `operations` array. `add` requires `text`; `replace`
   requires an existing `id` and `text`; `remove` requires an existing `id`.
   Reject extra fields, blank assertion text, unknown IDs, and repeated targets.
4. Stage all operations against a detached dictionary. New facts get generated
   IDs. Remove targeted facts; replace targeted text without changing its ID.
5. Normalize case/whitespace to suppress exact duplicate assertions. Existing
   insertion order wins duplicates. Paraphrase matching and semantic correction
   decisions rely on the extractor. A replacement with unchanged normalized text
   preserves the original record rather than refreshing provenance.
6. Embed changed assertions, validate dimensions/norms, enforce capacity, and
   commit the pending dictionary and counters. No-op extractions do not add support
   observations to an existing fact.

## Retrieval

Embed the question once. Rank all current facts by descending cosine similarity,
then most recent changed revision, then later dictionary position. Return
detached entries with rank, cosine score, and score type. There is no similarity
cutoff, historical search, or automatic neighbor expansion. Blank queries and
empty stores return no candidates. Asserted fact text is embedded directly,
without vector-store chunking.

## Failure behavior and limitations

Invalid responses and embedding failures propagate without committing pending
facts. Query embedding failure also propagates. Invalid k/capacity raises
`ValueError`. Long extraction prompts grow with the store; semantic interpretation
and speaker distinctions depend on the extractor, without the temporal store's
explicit same-speaker target validation. Removed/replaced text is irrecoverable
from this module. Direct callers without user metadata must pass user-only text.

## Source and verification

[FactStore.py](../../src/FactStore.py) and [Embeddings.py](../../src/Embeddings.py)
implement storage and similarity. [Semantic memory tests](../../tests/test_semantic_memory.py)
cover additions, corrections, retractions, deduplication, ordering, returned
copies, and atomic failures.
