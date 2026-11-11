# Mechanism consistency audit — 2026-11-11

## Scope

Reviewed the source/tool inventory (42 Python files), memory registry and factory,
benchmark configuration and lifecycle, question concurrency, request diagnostics,
artifact storage, saved-run history, resume, CLI, inspector, exports/imports,
frontend runtime labels, canonical specifications and CI checks. Historical plans
remain historical records rather than current implementation specifications.

The audit ran locally without hosting the application, invoking a provider, or
cancelling/resuming the user's active worker.

## Concrete mismatches corrected

| Area | Mismatch | Resulting contract |
| --- | --- | --- |
| CLI persistence | Web checkpoints were incremental while CLI checkpoints rewrote every payload. | Both use `write_snapshot` while active. CLI final output remains one portable inline JSON file. |
| CLI and inspector input | Raw JSON loaders rejected internal SQLite-backed manifests. | Both use the shared `read_json` loader; sidecars are required for internal checkpoints. Other offline analysis tools continue to consume portable exports. |
| JSON format | Readers differed on UTF-8 BOM and nonfinite numbers. | The shared reader accepts a BOM and rejects NaN/Infinity, matching finite-only writes. |
| Worker ownership | A terminal status could permit a new job while a thread or detached worker was finishing. | Creation/resume also checks live threads and the global detached-worker lease. Per-run deletion/lease guards remain authoritative. |
| Oversized upload | Flask's default HTML 413 response did not match JSON client expectations. | Structured JSON error includes the result-library path for large portable exports. The request limit remains unchanged. |
| Runtime labels | Aggregate question durations could be mistaken for elapsed time under parallelism. | UI calls them aggregate processing time and explains that overlapping durations do not equal elapsed time. |
| Documentation | Some current specs claimed snapshots cannot restore vectors and always rebuild memory, or used `src/instance`. | Specs distinguish inspection snapshots from exact-state archives, describe frozen restore and legacy rebuilding, and use `instance/benchmark_runs`. |

## Confirmed intentional differences

- All 15 memory factory choices implement the common memory interface. Benchmark
  capabilities cover the 14 memory architectures plus the two explicit baselines.
- Chat `no_memory` retains no entries. Its legacy benchmark alias defaults to full
  context, with question-only available explicitly.
- Current user policy fixes web/API/CLI execution at eight question workers,
  including resumed jobs. The earlier configurable limit was removed at the
  user's request; historical reports retain their recorded worker counts.
- Ingestion and local retrieval are sequential. Question answer/judge API calls
  may overlap after memory is frozen; every task joins before the next conversation.
- Exact-state archives retain logical state, vectors and pending buffers, while
  inspection snapshots omit vectors. Neither serializes credentials or services.
- SQLite is run-owned audit/checkpoint storage, not an added retrieval backend.
  Portable exports carry the complete archive; stripped polling responses do not.
- A completed frozen construction is reused on compatible resume. Partial
  formation without dependent predictions and legacy archives may require rebuilding.
- Provider retries and request accounting remain per question. Finished cases
  are retained and judge-only retries reuse the original paid prediction/context.

## Verification

- Full offline suite: **351 tests passed**.
- Added cross-entrypoint coverage for incremental CLI writes and portable final
  output, internal checkpoint resume and inspection, finite/BOM JSON handling,
  finishing thread/global lease ownership, JSON upload-limit errors and registry parity.
- Parsed all 42 source/tool Python files; checked `workspace.js` and `compare.js`
  syntax and Git patch whitespace.
- Existing Windows replacement, checkpoint durability, corruption, export,
  deletion, frozen resume and parallel-question regressions remain in the suite.
- The existing saved run passed read-only resume preparation with three workers
  and all 40 saved cases preserved; it was not started or modified by the audit.

These checks establish local behavior, not provider output quality, future API
capacity or browser layout. No live browser server or paid benchmark was started.
Already-running workers keep their loaded code until stopped cleanly and resumed.
