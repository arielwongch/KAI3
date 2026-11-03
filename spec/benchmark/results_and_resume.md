# Benchmark results, persistence, and resume

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.
Snapshot loading and recovery behavior reviewed and updated on 2026-11-02.
Result-library and named Compare export integration reconciled on 2026-11-02.
That implementation was committed and pushed to `main` as `8035e9b`. The
post-commit documentation check records the completed milestone without changing
the result schema, resume rules, or verification scope.

## Purpose and interfaces

Run snapshots preserve completed and partial results independently of live memory
instances. `BenchmarkJob.snapshot`, `restore`, and `resume`, plus
`BenchmarkStore.atomic_json` and worker controls, implement this feature.
The [benchmark workspace](../frontend/benchmark.md) lists the web endpoints.

## Stored data and exports

[Hybrid conditions](../memory/hybrid.md) additionally export component snapshots,
write usage, storage metrics, context allocations, and evidence coverage. They
use a distinct packing identity and a combined component prompt hash; shares and
component limits participate in the existing configuration hash/resume checks.

[Reranked vector runs](../memory/vector_store_reranker.md) export the pinned
reranker identity and both vector and reranker scores/ranks. Resume requires the
same model revision and window/scoring settings; candidate k participates in the
configuration hash.

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

Formation-inclusive comparison runtime was added on 2026-11-03. New cases retain
`execution_retrieval_seconds` and `execution_answer_seconds` across resumes,
including failed query attempts and provider retry waits. These cumulative
components are checkpointed with saved predictions before judging; judge-only
resume reuses them without adding the original query time again. Retrieval and
answer timers are recorded on errors as well as success. An ingestion-blocked
case records zero query work when none has occurred and preserves prior query
timing when a rebuild fails. Unknown legacy timing remains unknown. Existing
total-time fields retain their original definitions. The derived comparison
schema is now version 5; the source schema and protocol version are unchanged.
The cost update records `ingestion.preparation_seconds`, including module setup,
alongside the existing ingestion and write timers. Historical reports use their
recorded ingestion time without estimating missing setup time. Token and runtime
averages divide full recorded memory-plus-query totals by recorded question count
and exclude judging.
Version 4 ignores failed requests without reported tokens in token totals, while
retaining their original ledger records and any usage actually reported.
Version 5 adds separate context-only token totals, averages, and coverage. New
answer diagnostics also record context-only counts for unbounded and baseline
paths when the tokenizer is available. Recorded bounded counts are preserved.
See [Compare runtime definitions](../frontend/compare_runs.md#metric-meaning-and-coverage).

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

On Windows, workers use `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` with
redirected standard streams. `DETACHED_PROCESS` is deliberately excluded: a venv
redirector can start the base Python interpreter with a new visible console.
The Windows lifecycle regression checks console visibility inside that interpreter;
the launcher-exit test checks that independent execution still works.
For recurring popups, run `venv\Scripts\python.exe tools\watch_console_windows.py`
from an existing terminal. It records console process ancestry and visible windows
for five minutes in `instance/console-popups.jsonl`, without launching child shells.

### Snapshot validation and damaged-file recovery

`app.read_benchmark_snapshot` is shared by startup restoration and periodic
refresh. It reads UTF-8 JSON, requires an object, validates `run_id` through
`BenchmarkStore.path_for`, and requires the resulting filename to match the
snapshot's filename. This is an identity/object check, not complete result-schema
or resume-protocol validation. Both scans consider top-level `.json` files only;
`.input.json`, `.continue.json`, and files in recovery subdirectories are excluded.

Unreadable, malformed, or mismatched snapshots are skipped without modifying
their files; valid runs still load. Startup logs a warning beginning
`Skipping unreadable benchmark snapshot`, with the filename, reason, and guidance
to restore a valid JSON backup or move the file out of the run directory. It does
not log a traceback for these handled failures. Periodic refresh skips the same
failures silently to avoid repeating warnings on every poll.

The application does not repair or quarantine snapshots automatically. For a
merge-conflicted file, preserve the original and both valid variants before
manual resolution. Moving recovery material below a subdirectory of the store
excludes it from scans. Legacy schema-v1 variants remain non-resumable under v3;
removing conflict markers does not upgrade their protocol.

The runtime `instance/` directory is excluded from Git; shared reports belong
under `data/result/`. Removing previously tracked runtime files from the index
retains their local content. Environment and startup-message guidance belongs to
the [local setup specification](../local_setup.md).

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

The [Compare Runs workspace](../frontend/compare_runs.md) saves new uploads
directly as `data/result/<original-filename>`, preserving valid basename characters.
Older nested/UUID uploads remain readable and manageable. Duplicate names prompt
individually for Skip, Keep both with `(1)`, `(2)`, etc., or Replace a matching copy.
All library results have Rename/Delete controls; Download selected requests
separate JSON files. Renames retain their parent folder and bytes and reject
collisions. Reads/mutations reject traversal, absolute paths, unsafe names,
symlinks, and Windows junctions; the feature spec owns the full folder boundary.

Selection alone computes analysis without writing; Save computed metrics enriches
an existing library JSON in place. Enrichment fills calculable missing token/
storage fields and recomputes a versioned `comparison` object, preserving source
scores, predictions, protocol, and evidence. Labels/timings are not inferred.
These library files do not become resumable server jobs.

Benchmark reports offer [Export to Compare Runs](../frontend/benchmark.md#reports-and-inspection)
with a filename chosen before saving. Saved jobs fetch their full current export
snapshot once; imported reports copy the original JSON. Both then use the same
validated import/enrichment API and duplicate choices. Saving a comparison copy
does not modify the job, uploaded source, or the separate Export JSON behavior.

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
upgrade or modify their stored evidence/scores. The Compare Runs view explicitly
uses exported case counts as a fallback for its comparison completion/success
percentages when no nonempty question manifest exists; those counts do not
recover the original selected-question denominator. See its
[metric definitions](../frontend/compare_runs.md#metric-meaning-and-coverage).

Snapshots do not restore embedding arrays or serialize live module objects.
Malformed imported result files, incompatible resume settings, unavailable datasets,
and active-run conflicts produce explicit errors. Unreadable local run snapshots
follow the skip-and-warn recovery behavior above. Partial reports remain inspectable.
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

[Snapshot-restore tests](../../tests/test_snapshot_restore.py) cover conflicted,
empty, non-object, invalid-encoding, missing/invalid-ID, mismatched-filename, and
unreadable snapshots; unchanged file contents; control/archive-file exclusion;
valid-run restoration; and refresh tolerance. On 2026-11-02, these two tests and
the lifecycle, recovery, audit-regression, result-library, and result-analysis
modules passed **33 targeted offline tests** using Python 3.11.3, with no model
downloads or paid API calls. This was not a full-suite or clean Python 3.12 setup
check. A same-day follow-up installed Python 3.12.10 and requirements in a clean
`venv`, passed `pip check` and both snapshot-restore tests, and verified HTTP 200
for the app's four pages using a temporary server. See
[local setup verification](../local_setup.md#source-and-verification) for scope
and limits. That setup-only follow-up did not rerun the full suite. Later Compare
work recorded an earlier 138-test full offline run followed by 15 targeted result
tests and 14 frontend state tests. The subsequent final double-check passed all
143 offline tests after filename/dialog edge fixes and exercised saved-run and
imported-report exports in the browser with unchanged sources.
See [latest verification scope](../../UPDATES.md#verification-and-outstanding-work).


## Periodic memory and reranker compatibility (2026-11-02)

New periodic-mode reports record `memory_batch_settings` with the shared k,
latest-k update policy, and before-QA flush. Resume compares batch settings and
memory prompts. Reranked modes record the pinned model identity and retrieval
policy version; incompatible earlier cosine-only fact/hybrid runs require a new
run. Existing standalone reranker reports with matching model/configuration
remain eligible. Existing saved result files remain readable and are not rewritten.


## Deleting saved benchmark runs (2026-11-02)

`DELETE /api/benchmarks/<run_id>` permanently removes the selected stopped run
from the registry and deletes these exact files under the configured run store:
`<id>.json`, `<id>.input.json`, `<id>.log`, `<id>.cancel`,
`<id>.continue.json`, and `<id>.lease`. Missing files are accepted. Other runs,
backup files, the global worker lease, and separately exported result-library or
downloaded JSON files are not deleted. This operation never recursively removes
folders and rejects linked/non-file targets.

The API validates IDs and returns 400 for invalid IDs, 404 for unknown runs,
409 for active/finishing execution, and 503 for cleanup failures. It holds the
registry lock against resume/cancel/review mutations, checks the actual server
thread, and acquires any retained per-run worker lease before cleanup. Thus a
terminal status alone does not permit deleting a worker still finishing writes.
A recently queued worker remains protected by the existing startup grace policy.

The snapshot is removed last. On a file error the run remains listed with its
snapshot, so deletion can be retried; some earlier ancillary files may already
have been removed. Successful deletion detaches persistence and removes the
registry entry so normal restore/listing cannot resurrect the run. The UI asks
for confirmation before sending the DELETE request. See the
[benchmark workspace](../frontend/benchmark.md#delete-saved-runs) for the flow.
