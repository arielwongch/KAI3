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

## Reports and inspection

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
with sortable charts/table and metric tooltips.
The read-only import behavior described above applies to `/benchmark`.

## API contracts

| Endpoint | Behavior |
| --- | --- |
| `GET /api/benchmarks/dataset` | Read the bundled LoCoMo dataset |
| `POST /api/benchmarks` | Validate `{dataset, options}` and start one job; return 202/run ID |
| `GET /api/benchmarks` | List saved runs and resumability |
| `GET /api/benchmarks/<run_id>` | Poll full snapshot/status |
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
