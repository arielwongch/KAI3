# Compaction validation failure: 2026-11-12

Run: `50b659b0-bb2b-40ce-a6ed-8b2fd052f9d0`.

## Evidence and root cause

The supplied access log reports successful HTTP reads, not benchmark execution
success. The saved run has `status=completed`, but ingestion reports
`completed_with_errors`: five conversations failed and 50 of 100 questions were
blocked. The other 50 questions were answered and judged.

Every failed compaction received two complete (`finish_reason=stop`) responses
that exceeded the pinned benchmark tokenizer's hard target:

| Conversation | Hard target | First output | Second output |
| --- | ---: | ---: | ---: |
| conv-41 | 4767 | 5338 | 4906 |
| conv-42 | 4782 | 5032 | 4844 |
| conv-43 | 4725 | 5273 | 5144 |
| conv-47 | 4790 | 5300 | 5169 |
| conv-48 | 4783 | 5859 | 5357 |

The prompt requested 90% of the hard target, but a language model's estimated
length is not the benchmark wordpiece count. The retry repeated that same
requested length, adding only a generic instruction to shorten. It neither
reported the measured overshoot nor calibrated the requested allowance.
These ten rejected responses account for 146,309 reported provider tokens,
including input and reasoning; this is separate from benchmark text counts.
There is no evidence of HTTP transport failure in these compaction attempts.

## Affected path and repair

Repeated-mode `Compaction.write` stages a new turn, calls `_replace` at the
threshold, and validates the replacement before committing. Exhaustion rolls
back the write. Benchmark ingestion then saves the error, marks that
conversation's questions ingestion-blocked, and continues other conversations.
The same `_replace` serves one-shot benchmarks and manual chat compaction.

Compaction now allows three total generation attempts: the initial call and two
retries. This is fixed in code and has no UI, API, or CLI override. Over-budget
feedback includes the measured count and tightens the requested allowance by
`previous_allowance * hard_target / measured_count * 0.8`, floored and bounded
below by one. Incomplete output requests a shorter complete replacement.
Every attempt still reads the original staged source. The configured retained
percentage, hard target, output cap, source scope, and no-truncation rule remain.

Each attempt records requested length, validation reason, output, usage, and
timing. Exhaustion reports the final reason/count and preserves committed state.
Cancellation, persistence failures, and permanent provider errors are not retried
by this validation loop. Shared provider transport retries remain separate.

The source-identity check permits only the exact audited old/new compaction
versions across this repair. Other execution changes still fail closed. Resume
retains earlier code identities and ingestion costs. A read-only construction of
resume for the actual saved run confirmed five reusable successful memory builds
and 50 retained judged cases. Failed ingestion still rebuilds from raw source;
this change does not introduce partial-ingestion recovery.

## Verification

Offline regressions reproduce conv-41's exact target and rejected lengths, third
attempt recovery through benchmark QA, exhausted retries, token accounting,
unchanged source, unconfigurable attempt limits, incomplete output, rollback of
multiple staged operations, cancellation, chat, artifact validation, frozen-state
reuse, and exact source migration with rejection of unrelated source edits.
The full offline suite passed: **381 tests**, including the frontend regression
wrappers. `git diff --check` found no whitespace errors.

No saved run was modified, worker launched, server restarted, or paid request
made. Actual provider compliance remains probabilistic; impossible targets fail
explicitly instead of silently accepting oversized or sliced memory.
