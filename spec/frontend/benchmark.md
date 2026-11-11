# Benchmark workspace

Status: implemented behavior. Last checked against repository source: 2026-10-08.
Focused result-export and shared-shell update: 2026-11-02. These check dates are
not implementation or release dates.

## Purpose and state

`/benchmark` uses the shared shell with separate setup, running/review, and report
views. Browser state holds the parsed dataset, selected settings, and current run
ID (`kai3-benchmark-run` in localStorage). Server jobs and durable snapshots are
defined in [results and resume](../benchmark/results_and_resume.md).
Its sidebar/branding, collapse control, and mobile drawer come from the
[shared workspace shell](workspace_shell.md), also used by Chat and Compare Runs.

## Setup and run flow

Load the bundled dataset or upload LoCoMo JSON. Parse actual conversation IDs into
a searchable selection list; choose all or selected conversations, category filters,
and question limit. Choose exactly one of the supported
[conditions](../benchmark/lifecycle.md). Capability metadata exposes applicable
memory controls and removes irrelevant settings from submissions. Read-only
evaluation settings and a run summary show selected questions and answer/judge
call estimates; those estimates are not monetary pricing or total memory-call cost.

Submitting creates a server job and stores its run ID. Polling displays ingestion,
answering, judging, review, and finalization activity, plus progress and cancellation.
Optional memory review shows the ingested snapshot and requires explicit Continue
with its current token. A cancelled or failed run opens a partial report.

Opening a saved run immediately shows a small spinner and Loading label in its
sidebar row and a compact loading status in the main view. On success the row
stays highlighted with `aria-current`. Starting a new benchmark,
importing a report, or a failed open clears that selection. Restoring the saved
selection on page load uses the same loading flow. Late responses, including
switching A to B and back to A, cannot replace the latest view. An unsuccessful
open does not continue into a sidebar Resume action.

Active benchmarks retain one spinning progress icon; automatic progress/sidebar
refreshes do not flash additional spinners. Manual refreshes, dataset/report reads,
imports, exports, and pending actions use the shared
[loading indicators](workspace_shell.md#assets-and-verification).

## Delete saved runs

Each sidebar entry shows its saved memory settings (including retrieval k,
candidate pool, context allowance, and window/capacity where recorded). Expand
**Run configuration** to inspect all saved options, including question filters
and component overrides, without opening the report. Missing historical settings
are marked unavailable rather than replaced with the current setup values.
The history summary cache includes the recorded configuration; older cache versions
are rebuilt from their authoritative saved report.

Each Saved runs entry has a Delete action. It is disabled while the run is active
or its server thread is finishing. The confirmation identifies the architecture
and full run ID and explains permanent deletion of the saved result, dataset,
log, and control files; exported Compare Runs/downloaded copies are kept.
Keep run or Escape cancels without a request. While deletion is pending, controls
and Escape dismissal are blocked to prevent duplicate/ambiguous actions.

On success, refresh the list and show a deletion status. If the deleted run is
open, clear its report, localStorage selection, polling timer, and benchmark
inspector and return to setup. Deleting another run preserves the current view.
Out-of-order list responses cannot restore older sidebar contents. Errors stay
in the dialog for retry; the API rechecks execution state before any deletion.

## Reports and inspection

The report separates **Context tokens/question** from **Memory + answering
tokens/question**. Context is just the supplied conversation/memory text, excluding
the question, instructions, and output, counted with the benchmark tokenizer.
Its average and coverage are independent of provider-token cost. Historical counts
may be derived from exact saved context with the pinned local tokenizer; missing
text is not replaced with prompt usage or byte estimates.

Memory + answering tokens/question is total recorded memory-preparation plus answering
provider tokens divided by recorded question count. Average question runtime is
total recorded memory preparation, retrieval, and answering time divided by that
same count. Both exclude judging and include recorded rebuilds/retries. Failed
requests without reported tokens are ignored; reported usage still counts. Unknown
required measurements stay unavailable. Shared preparation is not charged once per
question; it enters the numerator once. The breakdown shows both numerators.
See [cost definitions](compare_runs.md#metric-meaning-and-coverage) for category
allocation and legacy timing limits.

The breakdown's Reported API tokens, Memory API tokens, Total ingestion time,
and Recorded processing time follow the same per-module lifecycle accounting as
Compare Runs. All recorded answer/judge usage counts even when prediction or
judge parsing failed. Ingestion IDs are deduplicated, conflicting records or
missing required measurements remain unavailable, and processing time prefers
cumulative `execution_total_seconds` over the earlier per-case timer. API and
processing lifecycle totals include judging; the headline cost/runtime averages
retain their exclusion of judging.

Reports show configuration/status, accuracy and completion metrics with denominators,
category summaries, efficiency/storage, failures, human-review status, and an
expandable question list. Category/status filters narrow question details containing
prediction/reference, supplied evidence, judge ratings/rationale, and diagnostics.
Unavailable values remain distinct from zero; active/interrupted results are provisional.

Secondary actions export results, export/import human review, inspect ingestion,
resume eligible saved jobs, or start another run. Stored runs, uploaded exports,
and the repository result library are different sources. Imported reports are
read-only views with unchanged re-export and no resume/review mutation controls.
Legacy report interpretation follows [evaluation](../benchmark/evaluation.md) and
[baseline compatibility](../benchmark/baselines.md).

**Export to Compare Runs** on the report opens a filename dialog before saving.
Saved jobs fetch their full current export snapshot once; duplicate retries retain
that same snapshot. Imported reports use a copy of the original JSON, preserving
source fields and leaving their read-only view unchanged. The initial filename
uses the imported basename, or the saved run's condition and short run ID.

Saving uses the shared multipart `POST /api/results/import` flow, including JSON
validation, folder/name restrictions, atomic persistence, and offline enrichment
of calculable token/storage fields and the comparison metrics. It does not invoke
models or infer missing correctness labels/timings. Name conflicts offer Skip,
Keep both with a numbered suffix, or Replace an explicitly selected existing
copy. Failures stay in the dialog; success refreshes the library picker and
offers **Open Compare Runs**. The separate **Export JSON** action retains its
unchanged original-file download behavior.

The sidebar groups Chat, Test Benchmark, and [Compare Runs](compare_runs.md)
above New benchmark and saved-run actions. Compare saves named results directly
to `data/result/`, handles duplicates and file management, and compares results
with a configurable scatter plot, independently sortable table, and metric tooltips.
The read-only import behavior described above applies to `/benchmark`.

## API contracts

| Endpoint | Behavior |
| --- | --- |
| `GET /api/benchmarks/dataset` | Read the bundled LoCoMo dataset |
| `POST /api/benchmarks` | Validate `{dataset, options}` and start one job; return 202/run ID |
| `GET /api/benchmarks` | List saved runs, resumability, and `deletable` |
| `GET /api/benchmarks/<run_id>` | Poll full snapshot/status; optional `analysis=1` adds derived metrics for stopped runs |
| `DELETE /api/benchmarks/<run_id>` | Delete a stopped run and its owned files; 200/deleted run ID |
| `GET /api/benchmarks/<run_id>/export` | Download saved result JSON |
| `POST /api/benchmarks/<run_id>/cancel` | Request cooperative cancellation |
| `POST /api/benchmarks/<run_id>/continue` | Continue pending ingestion review using `{token}` |
| `POST /api/benchmarks/<run_id>/resume` | Resume compatible saved work, using original dataset |
| `GET /api/benchmarks/<run_id>/review` | Export predictions for human rubric review |
| `POST /api/benchmarks/<run_id>/review` | Validate/import `{reviews}` and calculate agreement |
| `GET /api/results` | List allowed result-library JSON paths in filename order |
| `GET /api/results/file?path=...` | Read a validated library result |
| `POST /api/results/import` | Save the named comparison copy with enrichment and duplicate handling |

Analysis, saved-file downloads, upload persistence, rename/delete, and enrichment endpoints are
specified in [Compare Runs](compare_runs.md#api-contracts-and-failures).

## Failure behavior and limitations

Only one server job may be active; conflicting start/resume requests return 409.
Invalid input/settings return 400, missing runs return 404, and launch failures
return 503 with a retained failed-run record. Stale review tokens return 409.
Resume can request the original dataset when its saved input is missing. Provider
errors are shown with partial results and recovery guidance. A running job blocks
importing a report in the client. Importing JSON does not launch benchmark calls.

The workspace does not combine multiple architectures in one job. Human review
support does not imply an actual calibration study has occurred. Protocol behavior
and defaults are owned by the benchmark feature specs, not this UI specification.

## Source and verification

[index.html](../../src/index.html), [workspace.js](../../src/workspace.js),
[style.css](../../src/style.css), and [app.py](../../src/app.py).
[workspace_sidebar.html](../../src/workspace_sidebar.html) and
[workspace-shell.js](../../src/workspace-shell.js) provide shared navigation.
[Frontend state tests](../../tests/test_frontend_state.py),
[result import tests](../../tests/test_result_import.py),
[result library tests](../../tests/test_result_library.py), and
[lifecycle tests](../../tests/test_benchmark_lifecycle.py) cover these flows.

The implementation committed and pushed as `8035e9b` passed the full 143-test
offline suite. Earlier focused checks passed the expanded import/export DOM suite,
15 targeted result tests, and 14 frontend state tests. Coverage includes source
preservation, fresh saved snapshots, duplicate choices, invalid names, missing
saved runs, and reopening the dialog. Headless Chrome saved a renamed imported
report, verified derived answer/judge/memory token totals and UTF-8 storage bytes,
and exercised Keep both and Replace against a temporary library. Desktop/phone
previews showed no overflow or JavaScript errors; no user files or provider calls
were involved in that browser verification.
This post-commit documentation review did not rerun application/provider tests.


The periodic modes expose one window/update-interval setting (default 100 speaker
messages), with summary-size controls or fact candidate/retrieval/capacity controls
as applicable. All embedded modes except standalone Vector Store expose the
reranker candidate limit. Reports display the recorded candidate pool and model
identity; component snapshots retain per-store overrides.


## Saved-run deletion verification (2026-11-02)

The full 164-test offline suite passed, including eight backend deletion tests
and 20 frontend-state tests. Checks cover exact file ownership, stopped/active
runs, live worker leases, final thread checkpoints, cleanup failures/retry,
confirmation/cancel, report reset, and duplicate submission. Isolated Chrome at
1440px/390px exercised confirmation, cancel, actual deletion, disabled active-run
actions, and report/selection reset. Disk assertions verified removal of selected
fixture files and preservation of the active fixture and exported copy. Dialog
screenshots were visually inspected. No user runs or provider calls were used.
# Architecture selection focus and scrolling

Architecture-card labels establish a positioning context for their invisible
native radio inputs. This keeps focus inside the visible card when the benchmark
pane scrolls; the outer document must stay anchored to the viewport. Native
label clicks, Tab navigation, arrow-key selection, and card focus styling remain
available.

The isolated Chromium regression uses the real UI with synthetic read-only
endpoints and never starts a benchmark or accesses the result library:

```powershell
$env:PYTHON = '.\venv\Scripts\python.exe'
$env:BROWSER_ARTIFACT_DIR = 'instance/benchmark-scroll-fixed'
node tests/test_benchmark_scroll_browser.js
```

Node.js 22+, Python test dependencies, and Chrome/Chromium are required. Set
`CHROME_BIN` to override the executable; on Linux, the defaults are `python3`
and `google-chrome`. The test verifies real mouse/keyboard selection, settings
visibility, root/header/sidebar geometry, and scrolling to both ends at desktop
and phone widths, including collapsed desktop sidebars. DOM-only change events
do not exercise the native focus path responsible for the original defect.

## Execution and storage consistency (2026-11-11)

Web, API and CLI runs use a fixed maximum of eight parallel questions per
conversation, including on resume. The UI has no worker selector and the CLI has
no worker-count flag; client overrides cannot lower or increase the fixed limit. Ingestion and local retrieval stay
serialized. Answer/judge requests overlap only after memory is frozen and any
review pause is released. All tasks and checkpoints join before the next
conversation. `questions` progress includes `active_questions` and
`question_workers`; result order remains the original manifest order.

Aggregate processing durations can overlap and are not elapsed wall-clock time.
Stopped reports retain the worker count under `config.question_workers` and
`question_execution`. Resume upgrades older worker counts to eight while preserving
memory/model/prompt controls, completed cases and paid predictions.

Internal run checkpoints require their run-owned SQLite artifact database.
Exports remain self-contained inline JSON; normal polling omits payloads.
Uploads exceeding the configured request limit return a structured JSON 413
error. Large portable exports can be placed in `data/result` and loaded through
saved results without uploading their contents.

Failed status polls never implicitly clear localStorage, discard the selected
run or open setup. Transient failures, including legacy-server false 404s,
retry at 2/4/8/10-second intervals while preserving loaded progress or the loading
panel. Explicit nonretryable missing/corrupt responses stop automatic polling
and leave the error in the current view. New benchmark and confirmed local
deletion remain explicit reset actions; late callbacks cannot undo them.
