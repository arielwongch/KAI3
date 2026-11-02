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
references, embeddings, and capacity. Later turns can reference sequential
version IDs allocated by earlier turns. Superseded/corrected/retracted assertions
remain historical versions as in the existing temporal store. No state commits
until every turn succeeds. Failure leaves both tiers and pending batch unchanged;
benchmark ingestion failure blocks QA rather than using incomplete memory.

Retrieval returns long-term context followed by chronological recent entries.
Summary retrieval ignores the query. Fact retrieval uses the shared vector
shortlist/reranker policy. The benchmark applies its whole-record context token
allowance, including section labels; fitting all recent entries is not guaranteed.
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
