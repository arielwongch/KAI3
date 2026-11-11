# Benchmark false 404 and setup-panel reset — 2026-11-11

## Observed evidence

The same run detail URL returned 404 at 21:34:36 and 200 at 21:51:14, with no
redirect status in the supplied access log. The run's manifest, summary, input,
artifact database and lease were present during inspection. Its checkpoint
reported running with eight question workers and saved answers. A GET failure
did not imply that the worker or its persisted results had disappeared.

The access log records only HTTP status, not the lookup/read exception or the
list response body. It cannot identify the exact historical filesystem event.
The failure paths below were reproduced deterministically with temporary files.

## Backtracked flow

1. The browser opens a saved run, persists its ID in localStorage, and requests
   `/api/benchmarks/<id>?analysis=1`. The earlier list request can return 200 even
   while its asynchronous history index is still loading.
2. The detail route refreshes `HistoryIndex` and obtains `jobs.get(id)`.
   Registry membership was incorrectly used as proof of on-disk existence.
3. Several transient conditions can leave that registry entry absent:
   - A worker replaces the manifest after the index's initial fingerprint/read.
     `_install` correctly rejects the old read, but the caller previously gave
     up without a targeted retry or distinguishing a still-existing checkpoint.
   - Windows replacement can briefly hide a path from directory enumeration.
     The index previously pruned a `DiskJob` using that enumeration alone.
   - Read/permission failures were memoized under the same fingerprint as corrupt
     JSON. An unchanged checkpoint could therefore remain skipped until another
     worker save changed it. SQLite busy errors were also converted to permanent
     validation errors. A long compaction request can leave the fingerprint
     unchanged for a substantial interval.
4. If indexing produced no job, the endpoint returned a generic 404 even when
   the checkpoint existed or its worker still owned a lease.
5. The frontend explicitly excluded 404 from its retry branch, cleared the run
   ID/localStorage, stopped polling and showed benchmark setup. This was a DOM
   panel reset, not an HTTP redirect. A later successful request could not undo
   the earlier discarded selection without another user action.

## Fixes

- Probe the requested checkpoint directly; do not trust directory enumeration
  alone. Preserve indexed jobs through transient absence while a worker owns
  their lease. Real deletion remains protected against stale index resurrection.
- Retry one changed checkpoint on a detail request, preserving the fingerprint
  check rather than publishing a stale read.
- Do not quarantine transient OS or SQLite busy/I/O failures by fingerprint.
  Stable malformed data retains its existing isolated corruption handling.
- Distinguish retryable 503 (`benchmark_temporarily_unavailable`), unreadable 409
  (`benchmark_snapshot_unreadable`) and confirmed missing 404
  (`benchmark_not_found`). Error responses disable caching; 503 includes
  `Retry-After`. The same absence classification applies to other run actions.
- Preserve selection, last report/progress and localStorage on failed polls,
  including legacy-server 404 responses. Retry transient failures with bounded
  2/4/8/10-second backoff. Explicitly nonretryable errors remain visible without
  opening setup or looping requests.
- Ignore stale responses after run switches. Explicit New benchmark or deletion
  still resets intentionally. A late timer after reset sends no `/null` request.

## Verification scope

Backend regressions cover replacement during indexing, a targeted retry, an
unchanged read-locked checkpoint recovering without another write, SQLite busy
recovery, directory enumeration omissions, temporary live-manifest absence,
real missing files and stable corruption. Frontend regressions cover initial
404 recovery, retained live progress/selection, bounded backoff, definitive
missing-run handling, explicit reset and stale asynchronous responses.

Verification completed: all **360 offline Python tests** and **42 frontend
state regressions** passed, along with JavaScript syntax and patch formatting
checks. The reported run remained active with its worker lease held and 70 saved
cases during the final read-only inspection.

The application was not hosted or restarted, and the active worker was not
cancelled or resumed. Applying the backend fix requires the user's web server
to load the changed code; a hard refresh loads the frontend changes. A detached
benchmark worker does not need to restart for these history/UI fixes.
