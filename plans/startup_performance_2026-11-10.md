# Startup performance analysis and fix plan

Date: 2026-11-10. Status: implemented locally; validation recorded below.

## Evidence

Measured with the existing Windows Python 3.12 virtual environment and current
working tree. No model API requests were made. The script entry point was run
with `runpy.run_path('src/app.py', run_name='__main__')`; only `Flask.run` was
replaced by a timing probe, followed by a Flask test-client request to `/`.

| Measurement | First process | Second process |
| --- | ---: | ---: |
| Initialization through call to Flask.run | 13.308 s | 12.806 s |
| Saved-run reading and JSON parsing | 2.330 s | 1.963 s |
| First home-page request after initialization | 0.045 s | 0.044 s |

Both script runs used the repository-root `instance/benchmark_runs`, reading 21
snapshot files containing 113,378,557 bytes (108.1 MiB). Input/control files are
excluded by the restoration loop. These repeated runs do not establish a cold
disk-cache baseline or measure socket-bind time.

A separate `-X importtime` run importing `app` recorded:

- `nltk.stem`: 4.666 s cumulative, including NLTK's SciPy and scikit-learn imports.
- `openai`: 2.323 s cumulative, reached through RequestPolicy/API/MemoryFactory.
- Total `import app`: 8.140 s. Importing the module used `src/instance`, which
  contains much smaller snapshots, so this is not the exact script baseline.

Cumulative import timings overlap and must not be added indiscriminately or
subtracted from the separate script measurements.

## Causes

1. `app.py` eagerly imports Benchmark, ReAct, MemoryFactory, and HybridMemory.
   Benchmark imports NLTK solely for Porter stemming used in scoring. Factory
   imports pull in API and the OpenAI SDK; API and ReAct also construct separate
   clients at module scope. HybridMemory's bottom-level import of
   WindowHybridMemory provides another path to API through memory classes.
2. `restore_benchmarks()` runs at module scope before Flask starts serving. It
   reads every saved snapshot and `BenchmarkJob.restore()` deep-copies each
   parsed result. Parsing time above excludes these deep copies and worker checks.
3. `refresh_jobs()` rereads snapshots on benchmark requests, including files for
   in-process jobs that it discards only after reading. Moving restoration alone
   would leave this recurring latency in the benchmark interface.

Embedding and reranker models are already lazy. Neither torch, transformers,
nor sentence_transformers was loaded by the measured script startup. Tokenizer
and model downloads can delay first use, but did not cause these startup times.
The Flask reloader is already disabled. OneDrive/antivirus overhead is possible
but has not been isolated or demonstrated as the primary cause.

## Implementation sequence

1. Add a reproducible subprocess startup probe for the actual script entry
   point, with a readiness marker, bounded timeout, phase timings, and a separate
   first-page timing. Record the effective run-store path and compare a temporary
   empty store with a representative populated store. Preserve existing data.
2. Move architecture metadata (HYBRIDS, benchmark module/capability lists, and
   protocol constants) into dependency-light modules. Keep compatible exports
   where callers rely on them. Serve page routes using metadata only. Remove
   eager runtime imports from app.py; load chat and execution code at first use.
   Make MemoryFactory import only the selected implementation, accounting for
   Compaction and HybridMemory/WindowHybridMemory import paths as well.
3. Load NLTK and cache its existing PorterStemmer on the first scoring call.
   Preserve stemming behavior and metric outputs. Create provider clients lazily
   through a shared, thread-safe initialization path, with an injectable boundary
   for existing tests. Keep SDK imports out of page startup and preserve request
   policy behavior, configuration loading, cancellation, and accounting.
4. Replace eager full-report restoration with a lightweight run-summary index
   and load full snapshots on detail/export/resume access. Build or reconcile
   legacy summaries in a background task with explicit loading status. Update
   summaries atomically as jobs persist; serialize concurrent first loads.
   Preserve interrupted-run recovery, live worker leases, malformed-file
   warnings, and authoritative in-process state. Never restore an active worker
   as an interrupted job just because loading became asynchronous.
5. Make refresh incremental using file change detection, with an explicit
   refresh path for uncertain/external changes. Skip authoritative in-process
   jobs before parsing disk files. Avoid repeated report deep copies on list
   requests; retain isolation for mutable snapshots. Ensure changes made by
   detached workers remain visible and deletion cannot resurrect cached jobs.
6. Show initialization/loading progress for first-use execution and history
   reconciliation. Keep heavyweight warm-up optional and off the readiness path.

## Validation and acceptance

- Proposed target: actual-script readiness and `/` response within 2 seconds
  on this machine after OS cache warm-up, with both empty and populated stores.
  Confirm feasibility after the import split; report cold runs separately.
- In a fresh subprocess, page startup and page GETs must not import NLTK,
  OpenAI, torch, transformers, or sentence_transformers, initialize model/tokenizer
  artifacts, or contact a provider. Use structural assertions alongside timings.
- Measure first chat, first scoring, first history list/detail, and repeated
  polling independently so startup savings do not hide a new unreported stall.
- Retain exact score outputs and run relevant existing snapshot-restore,
  benchmark-recovery/lifecycle, chat-concurrency, diagnostics, result-library,
  and memory tests. Add focused regression coverage for concurrent lazy loads,
  incremental refresh, corrupt snapshots, and detached-worker updates.
- Test imports and the real script entry point: their effective instance paths
  differ today. Preserve the existing store locations during this performance
  change; any data-location migration needs a separate explicit design.

The initial investigation left application code and saved benchmark data
unchanged. Implementation followed the user's subsequent instruction.

## Implementation evidence

Dependency-light BenchmarkConfig/MemoryConfig metadata now serves page routes.
MemoryFactory imports implementations on demand; API and ReAct share a locked
lazy ProviderClient. NLTK Porter stemming initializes on the first score call.
BenchmarkHistory provides advisory per-run summaries, background indexing of
larger legacy reports, lazy detail loads, and fingerprint-based invalidation.
Workers persist summaries; deletion removes them. UI feedback covers first chat
initialization and pending history indexing. A force-refresh API remains available.

`tools/profile_startup.py` measures the actual script entry point with Flask.run
replaced by a readiness probe, without opening a listener or making API requests.
Three populated-store runs measured 0.776-0.836 s readiness and 0.043-0.049 s for
the home-page request. Three empty-store runs measured 0.770-0.895 s readiness.
All six performed zero snapshot reads and loaded none of the heavy libraries.
These are repeated runs with warm OS caches, not a cold-cache claim.

Temporary copies of all 21 reports (113,378,557 bytes) produced a 0.015 s initial
history-list response with `loading=true`, then 0.006 s repeated polling with no
full-report rereads. Recreating the index against the generated sidecars took
0.341 s with zero full-report reads. A selected report required one source read;
its measured detail response took 0.021 s (report size affects this time).
Original snapshot bytes matched the temporary copies after verification.

Deferred initialization was measured separately without making API requests:
provider construction took 2.775 s, then 0.000050 s on repeat; Porter F1 scoring
took 4.739 s initially, then 0.000124 s. Existing metric regressions retain score
behavior. These deferred costs remain first-use latency, not eliminated work.

Final verification: all 281 offline Python tests passed, including 14 startup,
cache, concurrency, and recovery regressions. The combined frontend-state,
comparison, and result-import run passed all 36 Node tests. Existing provider
failure/cancellation and worker-process recovery checks passed. No provider
requests were made during validation. Changes remain local and uncommitted.
