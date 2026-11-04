# Periodic window memory

Implemented 2026-11-02; changes remain local until committed.

`windowed_summarization` (Windowed Summary) and `windowed_fact_store`
(Windowed Fact Store) extend the existing recent-window retrieval/inspection
contract without changing Alpha or Gamma write policies.

One positive `window_size` controls both the recent window and update interval:
10 by default in chat, 100 in benchmarks. Factory callers use `max_items`.
One entry is a completed user/assistant exchange in chat and one labelled speaker
message in benchmarks. Blank or explicitly incomplete entries do not advance k.

After writes k, 2k, 3k, etc., update long-term memory from the latest k incoming
entries. Keep those entries in the recent window, so recent and long-term memory
can overlap. Before k entries, retrieval uses only the recent window. Batch
counters span benchmark sessions; each source retains its session/date metadata.
Benchmarks flush the remaining partial batch once before memory review and QA.
Chat does not automatically flush partial batches.

The summary combines the previous summary with the ordered batch in one LLM
call, using the existing size cap. Current facts use one extraction call per
batch with multiple add/replace/remove operations applied atomically to the
final current state. Assistant text remains context, not assertion evidence.
Current-fact provenance includes the original source entries for that batch.

Benchmark facts use one extraction call returning an ordered operations result
for each dialogue ID, including empty results. Apply results chronologically to
a detached store, validating source IDs, same-speaker targets, current-version
references, embeddings, and capacity. Additions and replacements declare unique
`result_ref` handles such as `new:job`; later turns can reference these handles
in `id` or `supporting_version_ids`. Python resolves handles to stored numeric
version IDs, including deduplicated additions. Numeric references must identify
versions supplied in the starting snapshot; the model never predicts allocated
IDs. Handles from the current or future turn, duplicate handles, evicted records,
and repeated resolved targets are rejected. Superseded/corrected/retracted assertions
remain historical versions as in the existing temporal store. No state commits
until every turn succeeds. Failure leaves both tiers and pending batch unchanged;
benchmark ingestion failure blocks QA rather than using incomplete memory.

Versioned batches use a standalone JSON prompt and a compact complete version
snapshot (ID, assertion, speaker, status, and observation session/timestamp).
Full source text and provenance remain stored locally. The extraction policy
`temporal-batch-handles-v1` bounds the base prompt plus serialized payload to
524,288 UTF-8 bytes and requests at most 16,384 output tokens with JSON output.
These extraction limits are separate from QA context/output limits and are not
claims about the provider's context capacity. Exceeding the byte bound fails
explicitly; facts are never silently truncated.

Malformed or truncated extraction results receive at most one validation repair
call from the unchanged starting snapshot. Every attempt is counted in memory
usage. Embedding and transport errors do not trigger validation repair; transport
retries retain the shared request policy. Failed attempts save private JSON
artifacts under ignored `instance/memory_failures/`, including the input, raw
response, prompt identity, provider metadata, and structured validation location.
Run ingestion diagnostics link artifact IDs without embedding raw text in UI
errors. Terminal failure preserves both tiers, pending entries, IDs, revisions,
and eviction counters. Reports include the extraction policy in batch settings;
resume requires matching settings and prompt identity. `ingestion_outcome`
distinguishes successful ingestion from completed runs with ingestion errors.

Retrieval returns long-term context followed by chronological recent entries.
Summary retrieval ignores the query. Fact retrieval uses the shared vector
shortlist/reranker policy. The benchmark applies its whole-record context token
allowance, including section labels. The shared window packing policy reserves
room for recall and shortens detached summaries to the actual remaining allowance,
including all formatting. Turns and facts remain whole records; fitting all
recent entries is not guaranteed. See [context packing](../benchmark/context_budget.md).
Questions and predictions are never written back.

Inspection includes architecture, window size, update interval, pending entry
count, write/flush policies, and long-term configuration, plus tagged entries.
The pending entries are already present in the recent window and are not counted
twice in logical storage. Reports record batch policy and prompt identities;
resume requires compatible settings. Existing exports remain readable.

Implementation: [WindowHybridMemory.py](../../src/WindowHybridMemory.py),
[FactStore.py](../../src/FactStore.py), and
[TemporalFactStore.py](../../src/TemporalFactStore.py).
Regression coverage: [periodic memory tests](../../tests/test_periodic_memory.py)
and [frontend state tests](../../tests/test_frontend_state.js).
