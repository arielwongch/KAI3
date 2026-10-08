# LoCoMo ingestion and question lifecycle

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

## Purpose

Protocol `locomo-controlled-v3` compares memory architectures on the same selected
conversations/questions. One job evaluates one condition. Equal answer-context
allowance controls supplied context size, not ingestion cost or stored information.

## Conditions and configuration

| Condition ID | Implementation | Stored representation | Selection for a question |
| --- | --- | --- | --- |
| `question_only` | `NoMemory` plus benchmark baseline path | Nothing | Empty conversation context |
| `full_context` | `NoMemory` plus benchmark baseline path | No module records; runner holds the transcript | Entire conversation in order |
| `sliding_window` | `SlidingWindow` | Last N original turns | Most recent retained turns |
| `summarization` | `Summarization` | One generated rolling summary | The same summary for every question |
| `vector_store` | `VectorStore` | Original turns and embeddings of their chunks | Turns ranked by their best matching chunk |
| `fact_store` | `TemporalFactStore` | Atomic assertions, historical versions, provenance, and embeddings | All retained versions ranked by assertion similarity |

| Control | Window | Summary | Vector | Temporal facts |
| --- | --- | --- | --- | --- |
| `memory_context_tokens` | 2,000 | 2,000 | 2,000 | 2,000 |
| `retrieval_k` | `null` (all) | Unsupported | `null` (all) | `null` (all) |
| `max_stored_entries` | 10; must be finite | Unsupported | `null` (unlimited) | `null` (unlimited) |
| `max_summary_tokens` | Unsupported | Defaults to context allowance | Unsupported | Unsupported |
| `summary_batch_size` | No effect | 20; configurable from 1 to 20 | No effect | No effect |
| `fact_history_mode` | Unsupported | Unsupported | Unsupported | `versioned`, required |

The two reference baselines reject memory budget, retrieval, storage, summary-size,
and fact-history controls. Positive counts reject booleans, zero, negatives, and
fractions. A summary cap cannot exceed its context allowance. The runner currently
normalizes `summary_batch_size` for all conditions, but uses it only for summary.

Storage capacity, candidate count, and supplied context size are independent.
For example, a vector store can retain 100 turns, consider only its first eight
ranked turns, and supply fewer than eight because of the token allowance.

The [memory component specs](../README.md) own each storage/retrieval algorithm.
[Baselines](baselines.md) define reference behavior and legacy aliases.
The default question limit is 10 per selected conversation; zero selects all
questions matching the selected categories. Selected conversations are fully
ingested even when only one question is requested.

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

All module state is process-local Python data. There is no memory database or
automatic restoration from a snapshot. Benchmark results can persist inspection
snapshots and diagnostics, but snapshots omit embedding arrays. Resume rebuilds
memory when needed; generated summaries/facts can differ on rebuilding. Cached
model weights and tokenizer artifacts are separate from conversation state.

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
