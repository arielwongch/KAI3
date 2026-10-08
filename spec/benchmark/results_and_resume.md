# Benchmark results, persistence, and resume

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

## Purpose and interfaces

Run snapshots preserve completed and partial results independently of live memory
instances. `BenchmarkJob.snapshot`, `restore`, and `resume`, plus
`BenchmarkStore.atomic_json` and worker controls, implement this feature.
The [benchmark workspace](../frontend/benchmark.md) lists the web endpoints.

## Stored data and exports

New exports use `schema_version=2` and `protocol_version="locomo-controlled-v3"`.
They retain condition, normalized configuration, dataset hash, selected-question
manifest/hash, protocol description, counting/packing identity, prompts/hashes,
models/settings, dependency versions, predictions, judge results, failure states,
and per-stage diagnostics. Model names identify provider endpoints, not immutable
provider weights.

Each conversation's memory record contains a detached logical snapshot and ingestion
diagnostics. Storage metrics include retained entry count, text UTF-8 bytes,
serialized snapshot bytes, vector chunk count, eviction count, and current versus
historical facts. These exclude embedding arrays and runtime overhead. Memory
LLM calls, usage, write time, and session storage growth are recorded separately
from answer and judge costs. Missing provider usage is unavailable rather than
zero. `api_cost_usd` remains null; there is no implemented price estimator.

Cases retain exact `supplied_context`, retrieved records, token/byte counts,
candidate/included/omitted counts, truncation state, provider usage, timings, and
errors. [Evaluation](evaluation.md) owns aggregate formulas and their denominators.

## Write and recovery flow

Web runs are stored under `instance/benchmark_runs/`. A run's `.json` snapshot
is atomically replaced via a temporary file. `.input.json` retains original
dataset and launch state for restart/resume. The run store contains results and
conversation data, not API credentials.

Default execution uses a server thread. `background=True` starts a detached
worker with the same Python environment; it writes snapshots/logs and uses a
lease plus cancellation/continuation control files. Server startup restores saved
runs. Active threaded runs interrupted by restart become `interrupted`; a live
detached worker remains authoritative on disk. Missing worker liveness turns an
active detached run into an interrupted report. Launch/persistence failures are
surfaced as failed runs rather than leaving a permanent queued state.

The web server permits one active benchmark at a time. Cancellation is cooperative,
not an instantaneous termination of a pending provider call. Browser closure
does not delete saved results. The CLI writes checkpoints to its selected output
file; it does not use the browser run registry.

## Read, import, and resume flow

Saved runs can be reopened/exported by run ID. Repository library JSON files under
`data/result/` and user-uploaded exports open as imported reports. Imports validate
shape/schema, preserve the original JSON for re-export, and do not create live
jobs. Resume and human-label mutation controls are unavailable for imported files.
Library reads constrain resolved paths to its root.

Resume uses the persisted original dataset first, then available in-memory data,
then a supplied original dataset as fallback. If unavailable, the API returns
`dataset_required`. It rejects mismatched dataset/manifest/config hashes, packing
policy, prompt hashes, tokenizer revision/loaded identity, and relevant model
identifiers. Configuration hashes cover budgets, k, storage, summary batches, and
fact history. Legacy protocols cannot resume into v3.

Previously completed cases are retained. Judge failures can retry judging the
saved prediction and context. Missing answers can require chronological memory
rebuilding, which may regenerate different summaries/facts. Prior memory snapshots
are retained in `previous_ingestions`; ingestion identity distinguishes reused
predictions from new contexts. A resumed run keeps its run ID and records resume
count and prior status. Saved batch settings are preserved; a missing legacy batch
setting is interpreted as per-turn construction subject to compatibility checks.

## Compatibility, failures, and limitations

Schema-v1 results remain readable with their original metrics. Fields absent from
old exports are unavailable unless unambiguously derivable; selected denominators
are not invented from saved case counts. Baseline labels follow
[baseline compatibility](baselines.md). Inspecting/importing old results does not
upgrade or modify their stored evidence/scores.

Snapshots do not restore embedding arrays or serialize live module objects.
Malformed result files, incompatible resume settings, unavailable datasets, and
active-run conflicts produce explicit errors. Partial reports remain inspectable.
Logical snapshot size is not a measurement of embedding-model RAM or total disk
usage. A completed execution is not evidence of a completed, matched scientific
comparison; outstanding experiment work is tracked in the
[controlled-comparison plan](../../plans/controlled_comparison.md).

## Source and verification

[Benchmark.py](../../src/Benchmark.py), [BenchmarkStore.py](../../src/BenchmarkStore.py),
[BenchmarkWorker.py](../../src/BenchmarkWorker.py), and [app.py](../../src/app.py).
[Recovery tests](../../tests/test_benchmark_recovery.py),
[lifecycle tests](../../tests/test_benchmark_lifecycle.py),
[import tests](../../tests/test_result_import.py), and
[library tests](../../tests/test_result_library.py) cover persistence/resume and
legacy or imported reports.
