# LoCoMo ingestion and question lifecycle

Workflow corrections reviewed 2026-11-12: malformed session-like keys and
nonempty conversations without recognized `session_N` arrays are rejected.
An explicitly empty conversation object remains supported for empty-memory
controls. The selected question manifest must be nonempty before launch.
User cancellation during write, periodic flush or compaction retains partial
construction and usage as cancelled; it does not fabricate ingestion-blocked
question failures. Untouched selected questions remain not attempted.

Storage metrics recurse through paired components and window/long-term tiers.
Parent serialized embedding bytes and chunk counts sum children once. Active
text, inspection JSON and serialized arrays remain separate measurements;
these do not measure resident memory or model weights. Window eviction counters
advance only on committed window changes.

Storage, concurrency, and resume contracts reviewed on 2026-11-11; see the
[mechanism consistency audit](../../plans/mechanism_consistency_audit_2026-11-11.md).

Status: implemented behavior. Last checked against repository source: 2026-11-02.
This check date is not an implementation or release date.

## Purpose

Protocol `locomo-controlled-v3` compares memory architectures on the same selected
conversations/questions. One job evaluates one condition. Equal answer-context
allowance controls supplied context size, not ingestion cost or stored information.

## Startup and saved-run history

Implemented 2026-11-10. Web startup does not restore full reports or import the
provider SDK, NLTK, or local model libraries. Shared provider-client construction
is serialized on first use; scoring retains NLTK Porter stemming with lazy
initialization. MemoryFactory loads the selected implementation on demand.

`GET /api/benchmarks` returns `runs` plus a `loading` flag. Each snapshot can have
an advisory `.summary.json` sidecar containing a versioned summary and its source
file's modification time, change time, and size. Unchanged summaries serve list
requests without reading full reports. Missing summaries for larger legacy
reports are built in a background thread; small reports are indexed inline.
`?refresh=1` explicitly rebuilds summaries. Detail, export, review, and control
requests reconcile their selected report; creation/resumption reconcile all run
statuses before enforcing the single-active-run rule.

Full reports load under a per-job lock and exported snapshots remain isolated
copies. Source changes invalidate cached reports; deleted files disappear from
the list. Background indexing rechecks source identity and in-process ownership
before installing a result. In-process execution remains authoritative. Detached
worker leases are checked even when a snapshot is unchanged, preserving active
reviews and detecting exited workers. Malformed reports are left untouched and
warned about during indexing; unchanged failures are not reparsed on every poll.
Both server and detached-worker persistence update advisory summaries. Deletion
includes the selected run's summary, with existing thread/lease guards retained.

## Conditions and configuration

| Condition ID | Implementation | Stored representation | Selection for a question |
| --- | --- | --- | --- |
| `question_only` | `NoMemory` plus benchmark baseline path | Nothing | Empty conversation context |
| `full_context` | `NoMemory` plus benchmark baseline path | No module records; runner holds the transcript | Entire conversation in order |
| `sliding_window` | `SlidingWindow` | Last N original turns | Most recent retained turns |
| `summarization` | `Summarization` | One generated rolling summary | The same summary for every question |
| `vector_store` | `VectorStore` | Original turns and embeddings of their chunks | Turns ranked by their best matching chunk |
| `vector_store_reranker` | `VectorStoreReranker` | Original turns and chunk embeddings | Cosine shortlist, cross-encoder ranking, final k |
| `fact_store` | `TemporalFactStore` | Atomic assertions, historical versions, provenance, and embeddings | Cosine shortlist, cross-encoder ranking, final k |

| Control | Window | Summary | Vector | Temporal facts |
| --- | --- | --- | --- | --- |
| `memory_context_tokens` | 8,000 | 8,000 | 8,000 | 8,000 |
| `retrieval_k` | `null` (all) | Unsupported | `null` (all) | `null` (all) |
| `max_stored_entries` | 10; must be finite | Unsupported | `null` (unlimited) | `null` (unlimited) |
| `max_summary_tokens` | Unsupported | Defaults to context allowance | Unsupported | Unsupported |
| `summary_batch_size` | No effect | 20; configurable from 1 to 20 | No effect | No effect |
| `fact_history_mode` | Unsupported | Unsupported | Unsupported | `versioned`, required |

The two reference baselines reject memory budget, retrieval, storage, summary-size,
and fact-history controls. Positive counts reject booleans, zero, negatives, and
fractions. A summary cap cannot exceed its context allowance. The runner currently
normalizes `summary_batch_size` for all conditions, but uses it only for summary.

The [reranked vector mode](../memory/vector_store_reranker.md) shares vector
capacity, final k, and context defaults, adding `candidate_k=50`. A null candidate
limit considers every retained turn. Final k applies after reranking; final `all`
means the whole shortlist. CLI/UI use `all` for null.

Storage capacity, candidate count, and supplied context size are independent.
For example, a vector store can retain 100 turns, consider only its first eight
ranked turns, and supply fewer than eight because of the token allowance.

The [memory component specs](../README.md) own each storage/retrieval algorithm.

The [compaction condition](../memory/compaction.md) independently controls retained
percentage and trigger tokens. One-shot mode compacts a declared raw source
window before QA; repeated mode compacts the active state during ingestion and
does not force a final flush. Its reader allowance is enforced without a second
lossy packing step, and successful frozen compaction states are reused on resume.
[Baselines](baselines.md) define reference behavior and legacy aliases.
The default question limit is 10 per selected conversation; zero selects all
questions matching the selected categories. Selected conversations are fully
ingested even when only one question is requested.

The [periodic window modes](../memory/periodic_window.md) add
`windowed_summarization` and `windowed_fact_store`: one window-size setting
(default 100) also controls the update interval. They ingest original entries
individually, update every k entries across sessions, and flush the remainder
before memory review or QA. `summary_batch_size` does not control these modes.
The fact variant requires versioned history and supports candidate/final-k limits;
the summary variant supports the existing summary cap.

All embedded retrieval except standalone Vector Store uses the shared reranker,
including facts and embedded hybrid components. `candidate_k` defaults to 50 per
store and accepts null for all; component overrides use `component_options`.

## Ingestion and answering

Implementation: [Benchmark.py](../../src/Benchmark.py),
[MemoryFactory.py](../../src/MemoryFactory.py), and
[MemoryEntry.py](../../src/MemoryEntry.py).

1. Create a fresh module for each selected conversation and condition. Never mix
   records across conversations. A benchmark job runs one condition.
2. Ingest the selected conversation completely before answering its questions.
   `question_limit` limits QA, not ingestion. Sessions are sorted by the numeric
   suffix in `session_N`; turns retain their order within each session. Dates
   label turns but are not used to reorder them.
3. Convert each turn to `MemoryEntry(text, metadata)`. Its text is:

   ```text
   [session_1 | <session date/time> | D1:1] Bob: <original turn text>
   Image caption: <blip_caption, when present>
   ```

   Metadata contains `type="benchmark"`, `user_text` equal to this formatted
   text, `speaker`, `timestamp`, `dialogue_id`, and `session`. Images contribute
   captions when available; the memory modules do not embed image pixels.
4. Window, vector, and temporal facts receive one write per turn. Summary receives
   one write per batch. Baselines bypass module writes.
5. For each question, construct context, then make a fresh direct answer request
   using the shared answer prompt. This path does not run the ReAct agent.
6. Do not write QA questions, generated answers, or judge responses into memory.
   Reference answers and annotated evidence are used after prediction for scoring,
   never to select or construct memory.

Live module state is process-local Python data. Inspection snapshots omit
embedding arrays, while the run-owned experiment archive retains exact logical
state, vectors and pending buffers. Compatible archived resumes restore that
frozen state; incomplete formation without dependent predictions and legacy
reports may require rebuilding. Cached model weights and tokenizer artifacts are
separate from conversation state. Audit SQLite storage is not a retrieval store.

Web, API and CLI entrypoints use a fixed maximum of eight question workers.
No worker selector or CLI flag is exposed; client overrides are ignored. Ingestion
and local retrieval are serialized; answering/judging can overlap after memory
is frozen. Every question and checkpoint finishes before the next conversation.
Older worker counts are upgraded to eight on resume without
changing the dataset, memory settings, prompts, or saved predictions.

## Execution state and failure behavior

The runner builds the complete selected-question manifest before ingestion.
It validates the dataset/configuration and initializes the shared tokenizer
before memory calls. Each question goes through retrieval/context construction,
answer generation, then judging. The answer prompt requires use of the supplied
conversation and abstention when unsupported. Model/prompt identities and settings
are recorded in the result.

Run states include `queued`, `running`, `waiting_review`, `completed`, `failed`,
`cancelled`, and `interrupted`. With `review_memory=True`, the web workflow pauses
after a conversation's ingestion and before QA. Continuing requires the current
review token. Cancellation is cooperative; partial results and the full manifest
remain available. The CLI rejects interactive review mode.

An ingestion error blocks the selected pending questions for that conversation.
Context/answer/judge failures remain distinct case outcomes; see
[evaluation](evaluation.md). Invalid or length-limited answers are not scored as
valid predictions. Judge retry can reuse a saved answer without regenerating it.
Threaded/detached execution and restart behavior belong to
[results and resume](results_and_resume.md).

## Interfaces, stored data, and diagnostics

`BenchmarkJob(data, options)` owns dataset/configuration, manifest, cases,
snapshots, progress, and cancellation/review state. `conversation_entries`
formats turns; `ingestion_batches` groups summary input; `direct_answer` consumes
the supplied context without ReAct. `BenchmarkJob.run()` executes the job.
Web endpoints and client state are listed in the [benchmark workspace](../frontend/benchmark.md).

Case diagnostics retain the exact supplied context and included entries, retrieval
counts, storage before/after, timings, provider usage, and failure stage. Ingestion
diagnostics separately retain memory calls, ingested turns, storage growth, and
write time. No annotated answer/evidence controls retrieval or generation.

## Source and verification

[Benchmark.py](../../src/Benchmark.py) implements this feature.
[Lifecycle tests](../../tests/test_benchmark_lifecycle.py),
[summary tests](../../tests/test_summary_benchmark.py), and
[controlled comparison tests](../../tests/test_controlled_comparison.py) cover
state transitions, ingestion, configuration, failures, and no QA write-back.

## Hybrid conditions

Delta, epsilon, and zeta are available alongside the original conditions. Their
component settings, batching, and context allocations are defined in the
[hybrid specification](../memory/hybrid.md). Summary hybrids batch only summary
updates; their vector/fact components ingest individual original turns.
