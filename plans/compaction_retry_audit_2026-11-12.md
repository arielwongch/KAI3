# Independent review of the compaction retry patch

## Findings, reproduced before repair

1. **High: candidate-archive errors lose known usage and fail to halt paid work.**
   `_replace` archived the paid response before recording usage. Its broad
   exception handler treated archive failure as unknown provider usage and
   re-raised an ordinary error. Benchmark ingestion could then continue paying
   for later conversations. Archive failures now use `CheckpointError`, which
   the existing benchmark fatal-error path recognizes. Returned usage is recorded
   once before attempting to archive the candidate. Unit and benchmark tests
   verify the original memory remains, known tokens remain known, no QA starts,
   and the second conversation makes no compaction call.

2. **Medium: empty truncated responses do not tighten the requested allowance.**
   An empty response with `finish_reason=length` matched `empty_response` before
   checking provider completion status. It repeated the same requested length.
   Incomplete finish reasons now take precedence, even for empty content. Nonempty
   incomplete output is measured for diagnostics, while remaining ineligible for
   acceptance.

3. **Medium: oversized appends validate against an insufficient constraint.**
   A 100-token incoming entry with a 50% percentage target and 20-token trigger
   could return a complete 30-token summary. `_replace` accepted it, but `write`
   immediately rejected it without using the remaining retry attempts. The
   oversized-append operation now validates against `min(percentage target,
   trigger)` and records that acceptance limit separately. The percentage target
   remains visible, and the write is still transactional. The regression now
   rejects the 30-token summary, retries, and commits a fitting replacement.

4. **Coverage gap: canned third-attempt success does not prove feedback helps.**
   The original test returned predetermined lengths regardless of the prompt.
   A new approximate-tokenizer fixture derives output length from the requested
   allowance. It fails the first attempt and recovers because the measured
   feedback actually changes the next allowance.

## Scope and integrity

The attempt count remains three total generations, with no user override.
Transport retries remain a separate existing policy. One-shot and manual
compaction keep their percentage limit; only oversized appends add the write
threshold as an acceptance constraint. No candidate is sliced, and incomplete
candidates cannot be committed. Semantic fidelity is not guaranteed by structural
validation.

The exact source-hash migration was updated for the audited implementation and
allows the original two-attempt and first three-attempt versions, in both newline
formats. Unknown execution edits still fail closed; previous identities remain
in resume provenance. Successful frozen states remain reusable. Failed ingestion
still rebuilds from raw source on explicit resume.

No live provider calls, saved-run changes, worker launches, or server restarts
were used for this audit.

## Verification results

All **386 offline tests passed**, with test-process exit code 0. This includes
frontend regressions, other memory modules, ingestion rollback, paid-response
accounting, benchmark lifecycle, and resume integrity. `git diff --check` passed.
A read-only resume construction using the actual reported run retained all 50
judged answers and five reusable successful memory builds.

## Second review: final transaction boundaries

Additional fault injection reproduced two durability defects:

- A final `checkpoint` callback raised an ordinary `OSError`, bypassing the
  benchmark's fatal-persistence classification. All compaction checkpoint
  callbacks now wrap persistence failures in `CheckpointError`, including the
  callback before a paid request. No request is sent if that first save fails.
- Manual compaction and repeated writes published entries/counters before
  `_mark_events` finished archiving the transaction. Failure there reported an
  unsuccessful operation while leaving changed memory. Finalization now runs
  inside the rollback boundary. Commit flags and transaction references are
  published only after every event snapshot has archived successfully. Failure
  restores entries, depth, ingestion/omission counters and peak token count;
  rollback diagnostics cannot retain a stale committed snapshot.

Regressions cover persistent archive failure in manual and repeated operations,
a transient failure on the second snapshot of a two-operation write, successful
rollback snapshots, and failures before and after generation. The source-hash
migration also retains compatibility with the previous audited version.

Second-review verification: all **390 offline tests passed**, with process exit
code 0, and `git diff --check` passed. A new read-only resume construction for the
reported run again retained five successful builds and 50 judged answers. No
saved run was changed and no paid request was made.
