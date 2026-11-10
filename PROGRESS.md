# Project progress

Original phase review: 2026-10-08. Latest implementation/status update: 2026-11-10.
The original five-item Phase 1 outline is preserved in
[the development-plan archive](plans/archive/initial_phase.md), first recorded
on 2026-09-15 in commit `df2e17f`.

| Original objective | Current evidence and limits |
| --- | --- |
| Shared memory interface | Implemented; see [interface](spec/memory/interface.md) |
| Four memory modules | Window, summary, vector, and current facts implemented; benchmark also selects temporal facts and separate baselines; see [components](spec/README.md) |
| Small agent loop | ReAct chat integration implemented; benchmark QA uses direct answering |
| Test modules on LoCoMo | Runner and mocked coverage implemented; a completed matched six-condition study is not established |
| Record latency, tokens, storage growth | Diagnostics/results implement these measurements; snapshots exclude embeddings/runtime, and missing usage remains unavailable |

This is an evidence-based status summary, not an assertion that every experiment
or acceptance criterion is complete. Use the [plan register](plans/README.md) for
dated milestones, dependencies, remaining work, and unscheduled proposals.
Current contracts are indexed under [spec/](spec/README.md).

## Decision-brief verification and comparison uncertainty - 2026-11-04

The [decision-brief validation](plans/decision_brief_2026-11-04.md) reproduces
the periodic-summary exports and distinguishes campaign usage from controlled
batching effects. Comparison schema 6 preserves missing failed-request usage as
unknown, exposes known recorded lower bounds and coverage, flags actual
filename/config mismatches on analysis, and separates current-snapshot storage
from latest successful-ingestion storage over the selected conversation cohort.
Original exports remain unchanged. Actual human calibration is still zero;
standalone confirmation and periodic-factor experiments remain unexecuted.
The audit follow-up plan now reflects current reserved-recall packing and
formation-inclusive accounting. These are implementation/evidence updates,
not new model-effectiveness findings.

The report-level follow-up is complete: live and imported reports display usage
lower bounds, missing-usage and rebuild coverage, storage cohorts, and local
filename/config warnings. Thirty frontend checks, import/export and comparison
tests, and rendering of all three saved periodic-summary exports passed. Source
exports remain unchanged; documentation is reconciled with the final behavior.

## Approved audit follow-up - 2026-11-03

Independent verification of `6679238` passed the original 165 offline tests.
The approved follow-up adds deterministic offline blinded-review export/import,
source identities, a separate private mapping key, and regression coverage for
recent-first packing, resume rejection, pool/final/packed trace separation, and
lifecycle accounting. See [review instructions](spec/benchmark/adjudication.md).
Original benchmark exports are unchanged; actual human labels remain pending.

Final verification: 179 offline tests passed, with a focused 10-test recheck after
full-history dataset validation was strengthened. The generated ignored review
packet contains 42 questions / 84 responses with zero human labels so far.

The [reranker confirmation contract](plans/reranker_confirmation.md) is prepared,
not frozen or executed. Calibration, power/sample-size review, verified frozen
states, analysis-script review, and paid-run approval remain prerequisites.

## Current workspace status — 2026-11-02

The implementation and its documentation were committed and pushed to
`origin/main` as `8035e9b` (**Add managed run comparisons and unify workspace UI**).
The verification below covers that implementation. This is a commit milestone,
not a tagged release or deployment.

| Area | Current behavior |
| --- | --- |
| Shared workspace design | Chat, Test Benchmark, and Compare use one sidebar template/script, common fonts/tokens, desktop collapse, and a mobile drawer; Compare uses the benchmark-style header and internal scroll area |
| Result storage | New JSONs save directly in `data/result/` with valid original basenames; legacy nested uploads remain usable |
| Duplicate names | Each conflict offers Skip, Keep both with `(1)`, `(2)`, etc., or Replace an explicitly chosen copy |
| File actions | Every library JSON has Rename and confirmed Delete; Rename keeps the parent folder/bytes and rejects collisions |
| Downloads | Download selected is the only download control and requests separate JSON files |
| Comparison | Filename-sorted library; one shared chart sort field; table defaults to name with one selectable accuracy/completion field; directions, missing-values-last, stable run colors, filters and coverage tooltips |
| Benchmark integration | Export to Compare Runs permits naming before saving, reuses enrichment/duplicate handling, and offers Open Compare Runs; imported/source reports remain unchanged |
| Folder boundary | JSON operations reject traversal, absolute/drive paths, unsafe names, symlinks, and Windows junctions; mutations share a lock |

Final verification passed the **full 143-test offline suite** on Python 3.12.10,
JavaScript syntax checks, and fresh headless Chrome checks at desktop/phone widths.
Earlier 15-result/14-frontend scoped checks and the 138-test run remain historical
evidence. Comprehensive accessibility,
cross-browser/state acceptance, real-provider validation, human calibration, and
a matched study remain open. See [updates](UPDATES.md) for the current summary.

The entries below are chronological implementation evidence. Earlier ZIP
downloads, UUID-folder imports, upload-only deletion, and browser-preview blocking
were superseded by the current behavior above; they are retained as history.

## Documentation reconciliation — 2026-11-02

Searched all **35 existing Markdown files** and reconciled **16 affected files**
across README, progress, maintained plans, indexes, setup, frontend specs, and
benchmark result/evaluation integration. Added [UPDATES.md](UPDATES.md), the
[shared-shell spec](spec/frontend/workspace_shell.md), and a
[complete per-file review](plans/documentation_review.md), bringing the inventory
to **38 files**. Nineteen unaffected protocol/memory/pointer/archive documents
were reviewed and retained; archived history was not rewritten as current status.
Earlier implementation/verification evidence is distinguished from latest checks
and remaining acceptance. This pass changes documentation only and does not claim
a fresh application test run.
Documentation checks passed: all 38 Markdown files are accounted for, all 397
local file/heading links resolve, heading IDs are unique, stale current-contract
descriptions were reconciled, and `git diff --check` passes.

## Final double-check — 2026-11-02

Rechecked code/contracts, reran the complete offline suite, and repeated the
shared-shell, chart/table sorting, tooltip, rename, upload/delete, separate-download,
and imported/saved benchmark-to-Compare browser flows. **All 143 tests passed**
after fixing malformed-Unicode filename validation, duplicate-name byte-limit
enforcement, and a queued-close/reopened-rename state edge case. Syntax and
documentation checks passed. Desktop/phone browser runs reported no JavaScript
errors or horizontal overflow; saved/imported source reports remained unchanged
and derived metrics were verified. All browser writes used temporary fixtures,
with no user result mutations or provider calls. The final-tree full-suite gap
noted in earlier entries is now closed; full accessibility and scientific/model
acceptance remain separate.

## Commit and post-commit documentation recheck — 2026-11-02

Commit `8035e9bb0026211c7dff1bc3cc2a97e1fd804b67` was pushed to `origin/main`.
The commit includes the workspace/result-library implementation, result exports,
runtime-file untracking, tests, and documentation. The nine new result reports
were parsed and credential-pattern checked before committing; the six modified
existing reports changed only their derived `comparison` objects. The result
analysis suite passed 10 tests with the added reports before the push.

The subsequent Markdown-only pass rechecked all 38 documentation files, corrected
pre-commit status wording, and aligned verification summaries with the full
143-test implementation run. Earlier audit counts and implementation history are
retained as dated records. No application behavior changed or application tests
were rerun during this documentation follow-up.

## Local setup and saved-run recovery update - 2026-11-02

Implemented clearer Windows/PowerShell setup instructions, Python 3.12 and
virtual-environment checks, and startup-message troubleshooting. The reported
command failures came from running the macOS/Linux block in PowerShell; subsequent
commands used global Python 3.11.3 because no virtual environment had been created.
See the [local setup specification](spec/local_setup.md).

The independent saved-run JSON error came from committed, unresolved Git conflict
markers. Preserved the exact original file and both valid legacy variants under
`instance/benchmark_runs/recovery/056d5e32-c971-4251-b38a-ae54883260e4/`, with a
SHA-256 manifest; neither variant was selected automatically. All **44** remaining
top-level JSON files parsed successfully. Removed nine runtime files from Git
tracking while preserving local content; `instance/`, `venv/`, and `.venv/` are
ignored. These changes were initially working-tree/index changes and were later
included in commit `8035e9b` on `main`; no tagged release is claimed.

Startup and refresh now validate snapshot object shape and run-ID/filename
agreement. Invalid files remain unchanged; startup warns with recovery guidance
without a traceback, and valid runs continue loading. See
[results and recovery](spec/benchmark/results_and_resume.md).

**33 targeted offline tests passed**, including two new snapshot-restore tests,
benchmark lifecycle/recovery, audit regressions, result-library, and result-analysis
coverage. No model downloads or paid API calls were used. This was a targeted run,
not a rerun of the full suite. That initial validation used Python **3.11.3**.

Follow-up Windows setup verification on 2026-11-02 installed Python **3.12.10**
for the current user, created an isolated `venv`, and installed `requirements.txt`.
`pip check` reported no broken requirements, both snapshot-restore tests passed
in the new environment, and a temporary `src/app.py` server returned HTTP 200 for
`/`, `/chat`, `/benchmark`, and `/compare`. The validation server was stopped;
no provider calls or model downloads were made. The README now includes the
WinGet install command, preserves an existing `.env` during Windows setup, and
uses UTF-8 for the environment check so the non-ASCII workspace path can print.
Basic Windows setup/startup acceptance is complete; a full-suite rerun on Python
3.12 and real-model/provider behavior were not part of this follow-up.

## Compare Runs update — 2026-10-30

Implemented `/compare` with local benchmark JSON uploads, atomic repository
storage, calculable missing token/storage fields, and saved enrichment/downloads.
Charts compare accuracy, tokens, storage, and runtime across selected results;
question-type filters and judged/selected coverage support interpretation.
See the [feature specification](spec/frontend/compare_runs.md).

The full offline suite passed **134 tests**, including new derivation, API,
bundled-export, and DOM chart checks. Browser preview was blocked by a sandbox
initialization error; manual visual/accessibility acceptance remains open. This
tooling update does not establish completion of a matched benchmark study.

## Earlier Compare library iteration — 2026-11-02 (superseded)

Refined `/compare` with clearer result cards, search-aware bulk selection, a
selection toolbar, run-color legends, useful empty states, and responsive chart
labels. **Download selected** downloads a single JSON or a ZIP containing only
selected files; duplicate basenames stay distinct inside the ZIP. New uploads
preserve original basenames, including parentheses, spaces, and Unicode, using
unique folders. Older sanitized names require re-upload to recover their names.

Uploaded files can be deleted through a confirmation dialog. The endpoint
restricts deletion to uploads; successful deletion updates selection and charts.
Cancellation and API failures retain the file. **All 138 offline tests passed**
on Python 3.12.10, including 10 targeted result tests and expanded Node DOM coverage for selection, download,
delete/cancel/failure, and filenames. Headless Chrome previews at desktop (1440px)
and phone (390px) widths showed no document overflow or JavaScript exceptions.
The selected-download button produced a valid ZIP containing the selected reports.
The built-in browser tool could not initialize its Windows sandbox; headless
Chrome provided visual inspection and selection/dialog checks instead. No model
or provider calls were made. See the [comparison specification](spec/frontend/compare_runs.md).

This iteration's ZIP/unique-folder/upload-only behavior was superseded later on
the same date. It does not describe the current library contract.

Duplicate-upload follow-up: matching filenames now prompt individually for
**Skip**, **Keep both** with the first available `(1)`, `(2)`, etc., or **Replace**
an explicitly chosen existing copy. Conflicts make no write until resolved;
replacement atomically updates the chosen file and its loaded comparison data.
Case-insensitive detection includes saved results and legacy uploads. **12
targeted result tests passed**, including per-file batch choices, stale/invalid
replacement targets, persistence failures, and Escape. A headless Chrome test
against a temporary library exercised skip, numbered duplication, and replacement
and verified the resulting files and selection. Desktop and phone dialog previews
showed no overflow or JavaScript exceptions. No user result files were changed
by this browser test.

Chart-tooltip follow-up: hovering a bar now shows the filename, module, value,
filter scope, and metric-specific coverage/totals. Storage explicitly retains
whole-run scope. Keyboard focus and touch expose the same details; zero and
unavailable rows remain inspectable. The expanded Node DOM suite passed, covering
values, scopes, missing data, dismissal, and viewport placement. Headless Chrome
verified hovering all four charts, focus/Escape, and phone tapping, with no
JavaScript exceptions or tooltip overflow. Browser checks used temporary fixture
results and did not change user result files.

Shared-library follow-up: new uploads now save directly to `data/result/` with
their original basenames. Existing, uploaded, and legacy nested results share
download/rename/delete controls. Selected files download as separate JSON files;
ZIP generation was removed. Load, refresh, and rename sort by displayed filename.
Rename keeps the parent folder and bytes, rejects name collisions, and preserves
selection and loaded charts. Duplicate skip/number/replace prompts remain.

A shared path guard confines library reads and writes to JSON paths under
`data/result/`, rejecting traversal, absolute/drive paths, unsafe names, symlinks,
and Windows junctions. All file mutations use the same lock. **15 targeted result
tests passed**, including expanded DOM checks and a real Windows junction test
that left an external sentinel unchanged. Headless Chrome verified rename,
shared-folder upload, sorted refresh, legacy-file deletion, and two separate JSON
downloads with expected filenames and contents. Desktop/mobile visual checks
showed no overflow or JavaScript errors. All browser writes used temporary fixture
files; existing user library files were not migrated or modified by verification.

Sorting/download-control follow-up: file cards now expose Rename/Delete only;
Download selected is the single download action. A shared chart sort selector
orders all four graphs by name, accuracy, tokens, storage, or runtime, with a
direction control. The accuracy table defaults to name ascending and separately
selects one name/category-accuracy/completion field and direction. New choices
replace the previous field. Missing values stay last, ties keep name order, and
run numbers/colors remain consistent through sorting. The expanded Node DOM
suite passed, and headless Chrome confirmed behavior and desktop/phone layout
without JavaScript errors or document overflow using temporary fixture data.

Benchmark-to-Compare export follow-up: report actions now include **Export to
Compare Runs**, with an editable filename before saving. Saved runs fetch their
full export snapshot; imported reports copy their original JSON. Both use the
existing folder-restricted import API to compute missing calculable metrics and
handle Skip/Keep both/Replace conflicts. Success refreshes the result picker and
offers Open Compare Runs; the original report and Export JSON behavior remain
unchanged. **15 targeted result tests and 14 frontend state tests passed**.
Headless Chrome verified named persistence, derived token/storage metrics, source
preservation, duplication/replacement, and desktop/phone dialog layout using only
temporary files, without provider calls or JavaScript errors.

Compare workspace design follow-up: Compare Runs now uses the shared sidebar
template, navigation script, fonts, design tokens, benchmark-style header, and
internal content scrolling. Its cards, controls, table, charts, and dialogs use
the same compact charcoal/lime styling as the other workspaces. Existing compare
features remain covered by their DOM suite. Shared navigation supports desktop
collapse and a mobile drawer with backdrop/Escape dismissal and focus handling.
**15 targeted result tests and 14 frontend state tests passed**. Headless Chrome
verified the shell on all three pages and Compare's library, sorting, tooltip,
rename, and desktop/phone layouts, with no horizontal overflow or JavaScript
errors. Browser checks used temporary fixtures without changing user result data.


## 2026-11-02 - Local periodic-memory, reranking, and dot-plot update

Implemented the approved two periodic window modes, shared embedded-store
reranking with standalone Vector Store preserved, and one selectable dot plot.
The [updates log](UPDATES.md#local-approved-implementation---2026-11-02) records
scope and verification. Full offline suite: 156 tests passed; frontend-state
coverage includes 16 Node tests. Desktop/phone browser checks at 1440px/390px used
temporary synthetic results and no provider calls. Changes remain local and
uncommitted; real-provider validation and a matched study are not claimed.


### 2026-11-02 - Configurable scatter and typography revision

At the user's revised request, replaced the single-metric run-row plot with a
numeric x/y scatter plot: tokens on x and accuracy on y by default, with all four
existing metrics available on either axis. SVG text stays in CSS pixels using
the surrounding workspace font sizes/styles. Coincident and missing measurements
remain inspectable. The 15 affected result tests, expanded DOM checks, and
1440px/390px headless browser checks passed with synthetic fixtures and no model
calls; the earlier full 156-test run predates this chart-only revision.


## 2026-11-02 - Saved benchmark run deletion

Added confirmed per-run deletion from Saved runs and a DELETE API that removes
only the chosen run's snapshot, saved dataset, logs, and controls. Runtime state,
thread completion, and worker leases protect running/finishing work; exported
copies remain separate. Deletion shares mutation locking and preserves a snapshot
for retry after file errors. Full offline suite: 164 tests passed, including eight
new backend deletion tests and 20 Node frontend-state tests. Chrome smoke checks
at 1440px/390px used synthetic runs only and verified confirm/cancel, active-run
guards, file removal, report/selection reset, and preserved exported data. Changes
remain local and uncommitted.
# 2026-11-10 - Compaction memory

Implemented the approved standalone `compaction` architecture with configurable
retained percentage, one-shot/repeated operation, independent token triggers,
explicit reader-budget enforcement, and transactional failure/cancellation.
Chat includes manual compaction; benchmark/terminal CLIs and Compare Runs expose
the new controls and measurements. Frozen successful states are reused on resume;
attempt costs remain separate from reuse and unknown usage stays unknown.
The sweep helper prepares independent conditions and frozen sources without
provider calls by default. See the [specification](spec/memory/compaction.md) and
[research decision record](plans/compaction_research_2026-11-10.md).

Final offline verification: **267 Python tests passed** (including the frontend
runner with **33 Node cases**); the expanded comparison UI checks also passed.
Headless Chrome checks at 1440px and 390px verified Chat/Benchmark controls and a
synthetic compaction scatter plot, with no document overflow or JavaScript
exceptions. All six screenshots were visually inspected. Preview artifacts/logs
are under ignored `instance/`; existing results were not changed. No paid
provider experiments, model training, or adaptive-policy effectiveness claims.
Changes remain local and uncommitted. Restart the server to load the new module.

# 2026-11-10 - Startup performance

Implemented lazy execution imports, a shared provider client initialized under a
lock, lazy Porter stemming, summary-based saved-run history, background legacy
indexing, lazy full reports, and incremental refresh. Existing in-process job
authority, worker leases, report isolation, and recovery/deletion guards remain.
First-chat/history loading feedback and a bounded entry-point probe were added.

Measured script initialization fell from 12.806-13.308 s to 0.776-0.836 s in
repeated populated-store runs. Startup performs no snapshot reads or heavy
library imports. Temporary copies of all 21 reports (108.1 MiB) verified 15 ms
initial history listing, 6 ms repeated polling without full-report rereads, and
on-demand selected-report loading. Original reports were preserved. Provider
construction and scoring retain measured first-use costs of 2.775 s and 4.739 s.

Final checks: 281 offline Python tests and 36 combined Node tests passed. No
provider requests were made. See the [implementation evidence](plans/startup_performance_2026-11-10.md).
Changes remain local and uncommitted; restart the server to apply them.
## 2026-11-10 - Benchmark architecture scroll fix

Anchored hidden architecture radios to their cards with `position:relative`.
This fixes native focus scrolling the outer document and moving the entire
application upward after selecting lower cards such as Epsilon or Compaction.
The [diagnosis and resolution](plans/benchmark_module_scroll_fix_2026-11-10.md)
record the cause and evidence.

The reusable isolated Chromium regression passed 140 real clicks, 112 keyboard
selections, and 266 geometry checks across four desktop/phone viewports and
expanded/collapsed desktop sidebars. Wheel scrolling reaches both ends without
refreshing; root/header/sidebar displacement stays zero. A temporary browser-only
reversion reproduced a regression failure. All 34 Node frontend cases and the
comparison UI checks passed. Focused CSS validation only; no full Python-suite
rerun, provider calls, or user-result modifications. Local/uncommitted.
## 2026-11-10 - Default reader allowance

Raised the new-run memory context allowance from 2,000 to 8,000 benchmark tokens
across benchmark configuration, chat hybrid/compaction defaults, constructors,
CLI, and sweep preparation. Benchmark summary caps follow the reader allowance
when unspecified; explicit settings and saved runs remain authoritative.
Compaction trigger tokens remain independently configurable. Updated current
documentation and existing default-dependent regression expectations. No saved
results or provider experiments were changed.

Validation: all 281 offline Python tests passed, including the frontend runner;
all 34 Node frontend cases passed. `git diff --check` passed. Local/uncommitted.

## Experiment recording - 2026-11-10

Follow-up: the three paper-audit priorities are implemented in the separate
[compaction evaluation workflow](spec/benchmark/compaction_evaluation.md): aggregate
compression factor/weighted retention, frozen-output evidence annotations with
human/imported-judge provenance and calibration, and paired conversation-clustered
campaign intervals. Full offline suite: 317 passed; the subsequently expanded
evaluation suite: 18 passed. Frontend syntax/whitespace checks passed. No existing
results, paid experiments, commits or pushes. See the
[implementation evidence](plans/compaction_evaluation_implementation_2026-11-10.md).

Completed primary-source research, a gap audit and concrete design before local
implementation. Added run-owned hash-checked archives, frozen logical state across
architectures, exact compaction attempts/rollback artifacts, prediction-context
identity, compatible resume (including detached workers), portable exports and
offline inspection. Existing work and results were preserved; no paid experiments,
commits or pushes. See the [audit and file inventory](plans/experiment_recording_2026-11-10.md)
and [recording workflow](spec/benchmark/experiment_recording.md).

Validation: 301 offline tests passed, including 19 recording acceptance tests and
existing frontend runners. Both frontend JavaScript syntax checks, whitespace
checks and inspector CLI help passed. Exact local reconstruction is distinct from
identical stochastic provider output; growth, weights, legacy and upload limits
are documented.
