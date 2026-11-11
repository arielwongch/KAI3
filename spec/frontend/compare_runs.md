# Compare Runs workspace

Refresh behavior reviewed 2026-11-12: explicit Refresh reloads selected reports
and invalidates unselected cached reports even when filenames are unchanged.
Per-file reload errors remain visible and the failed file's old metrics are
removed; its selection is preserved for retry. A generation counter prevents
older requests from replacing refreshed content. Successful upload responses
can be retained while refreshing the filename list after an upload.

Status: implemented behavior. Updated 2026-11-02. Automated API/DOM checks and
headless Chrome previews at desktop and phone widths cover the library refresh.

## Purpose and navigation

`/compare` provides offline analysis of benchmark result exports. Home and the
Chat/Benchmark sidebar link to **Compare Runs**. All three pages share the sidebar
template and navigation behavior, including active-page styling, desktop collapse,
and a mobile drawer with backdrop/Escape dismissal and focus restoration. Compare
also offers in-page library/comparison links and a Home link. It does not launch
jobs, invoke models, or resume uploaded results. Common shell behavior is owned
by the [shared workspace specification](workspace_shell.md).

The page loads shared `style.css` design tokens, DM Sans/Space Grotesk typography,
branding, and the benchmark-style header and internal scroll area. Scoped
`compare.css` supplies its library, charts, table, and dialog layouts using the
same charcoal panels, lime actions, borders, radii, and compact control sizing.
The oversized standalone hero and horizontal navigation have been removed.
Content-width queries stack library cards/charts and controls when the sidebar
leaves a narrow content area. Existing comparison behavior is preserved.

## Library, upload, and save flow

The library recursively lists JSON files under `data/result/`, sorted by displayed
filename (case-insensitive, with numeric ordering) on load, refresh, and rename.
Uploaded and existing files have the same saved-JSON cards and management actions.
Search filters filenames; checkboxes select multiple files. **Select all visible** adds only
search matches; **Clear selection** clears all selected files, including hidden
matches. A selection toolbar shows the total and enables save/download actions.
Selecting a file loads its enriched analysis without writing it. A file containing
multiple modules contributes one
comparison row per module. Selection and loaded reports are page-local and are
not restored after a browser reload.

Upload accepts multiple benchmark `.json` exports, each submitted as a separate
multipart request. The server validates an object with a `cases` array, computes
available missing fields, and atomically saves a new file under
`data/result/<original-filename>`. The original basename preserves parentheses,
spaces, Unicode, and extension case; folder paths and unsupported filesystem
characters are rejected. If a basename already exists
anywhere in the result library (case-insensitive, including legacy upload names),
the server returns a conflict without writing. Each conflicting file gets its
own dialog: **Skip this file**, **Keep both**, or **Replace existing**. Skip and
Escape leave the existing file unchanged and continue the batch. Keep both saves
the first available `name (1).json`, `name (2).json`, etc. Replace atomically
overwrites the explicitly chosen matching library path, including a saved result
if selected. If older copies already share a basename, the dialog lets the user
choose the replacement target. Replacement refreshes the loaded analysis and
selects the replaced file without creating another library entry.

The server rechecks conflicts and numbered names when saving. A changed or
removed replacement target cannot silently redirect a write to another file.
New copies use the shared result folder. Existing nested and legacy UUID-prefixed
uploads remain usable and expose the same actions; names
already sanitized by older imports cannot be reconstructed and require re-upload.
The app's request limit is 32 MiB. Uploaded files are selected immediately;
individual failures appear in the status message while other uploads continue.

Benchmark reports can also use **Export to Compare Runs** to choose a filename
and save through the same validated import/enrichment endpoint. Saved jobs supply
their full export snapshot; imported reports supply an unchanged copy of their
original JSON. The benchmark dialog handles the same duplicate choices and
provides a link to `/compare` after saving. See [benchmark reports](benchmark.md#reports-and-inspection).

**Save computed metrics** explicitly enriches and atomically updates selected
library files in place. File cards contain **Rename** and **Delete** only;
**Download selected** is the sole download control. It requests each selected file separately
and saves each response as a JSON download with its displayed filename. It never
creates a ZIP. Individual failures are reported while other downloads continue;
the browser may request permission for multiple automatic downloads. Legacy
same-name copies retain their names; any local download collision is managed by
the browser. Enrichment calculated only during selection must be saved first to
appear in a download. These files are separate from resumable jobs under
`instance/benchmark_runs/`.

Every result card exposes **Rename** and **Delete**. Rename takes a JSON basename,
keeps the current parent folder and file bytes, and rejects existing names with
409 rather than overwriting. Success updates the sorted library, selection,
cached report key, legends, and charts; errors remain in the rename dialog.
Cancellation leaves the file unchanged.

**Delete** uses a filename-specific confirmation
dialog. Cancellation, including Escape, leaves the file unchanged. A successful
delete removes the file from disk, selection, loaded analysis, and charts; errors
retain it and show a status message. Deletion is available for every library JSON,
including preexisting results. Library controls are disabled during
operations to prevent conflicting changes.

All library reads and mutations share one path guard restricted to the configured
`data/result/` root. It accepts canonical relative JSON paths and rejects absolute
and drive paths, `..`/`.`/empty components, backslashes, control characters,
alternate-stream colons, symbolic links, and Windows junctions. Listing does not
traverse linked folders. Upload and rename accept a basename only, reject reserved
filesystem/device names, and limit names to 200 UTF-8 bytes. Rename cannot move a
file into another folder. Imports, replacement, enrichment, rename, and deletion
use the same mutation lock. These controls protect the library API's folder
boundary; they do not provide operating-system isolation from other local programs.

## Enrichment and JSON contract

`ResultAnalysis.enrich_report` copies the report and preserves existing source
values. Missing or null fields are filled only when the required inputs exist:

| Destination | Required source and calculation |
| --- | --- |
| `cases[].diagnostics.answer_tokens` | `prompt_tokens + completion_tokens` |
| `cases[].diagnostics.judge_tokens` | `judge_prompt_tokens + judge_completion_tokens` |
| `memories[].ingestion.memory_tokens` | `memory_prompt_tokens + memory_completion_tokens` |
| `memories[].ingestion.final_storage.stored_text_bytes` | Sum of UTF-8 bytes of all snapshot entry texts |
| `memories[].ingestion.final_storage.stored_entries` | Number of snapshot entries |

Numeric inputs must be finite and nonnegative; booleans are not token or size
counts. Storage derivation requires an entries array whose records all contain
text strings. Missing correctness labels and timings are not inferred.

The report's derived `comparison` object is recomputed with `version: 6`,
`added_fields` (paths of filled fields, retained across repeated enrichment),
`definitions`, and `rows`. Each row contains `module`, `overall`, and `categories`
keyed by category string. Groups expose:

- `case_count`, `selected_count`, and `judged_count`;
- `accuracy_percent`, `completion_percent`, and `success_percent`;
- `mean_question_tokens`, `total_question_tokens`, and `token_count`;
- `mean_context_tokens`, `total_context_tokens`, and `context_token_count`;
- `mean_question_seconds`, `total_question_seconds`, and `runtime_count` retain
  their legacy question-only timing definition, including judging;
- `runtime`, containing formation-inclusive timing used by the chart and runtime
  breakdown table.

Overall groups additionally expose `stored_text_bytes`, `storage_count`, and
`memory_count`. Existing scores, schema/protocol identifiers, predictions, and
evidence remain unchanged; the comparison object has its own version.

Each `runtime` object exposes `count`, `record_count`, `formation_seconds`,
`retrieval_seconds`, `answer_seconds`, `total_seconds`, and corresponding
`mean_formation_seconds`, `mean_retrieval_seconds`, `mean_answer_seconds`, and
`mean_total_seconds`. Each mean divides its complete component total by the
recorded question count. Missing required measurements make that total and mean
unavailable; a subset of measured questions does not become the denominator.

Overall `runtime` also exposes `total_formation_seconds`, `formation_build_count`,
`formation_runtime_count`, `unallocated_formation_seconds`,
`conflicting_ingestion_ids`, and `recorded_total_seconds`. These run-level fields
are unchanged by category filters. `recorded_total_seconds` adds all recorded
formation to cumulative retrieval and answering, excluding judging, including
formation for conversations without recorded cases. It remains unavailable when
any required timing is missing. Overall `total_seconds` equals this run total;
`allocated_total_seconds` retains the sum of conversation-allocated question
costs. Category `total_seconds` sums the allocated costs of that category.

## Metric meaning and coverage

Judged cases have saved binary `correct` values of zero or one. Judged accuracy
is `100 × correct / judged`. Completion is `100 × judged / selected`; success is
`100 × correct / selected`. A nonempty question manifest supplies selected counts,
including unattempted questions. Without one, exported case counts are the
explicit fallback; they do not establish the original selection or failure-aware
benchmark denominator. A zero denominator produces an unavailable percentage.

The Benchmark report and Compare charts use these run-level averages:

```text
tokens per question = (total memory tokens + total answering tokens) / recorded questions
average runtime = (total memory preparation + retrieval + answering time) / recorded questions
```

Both exclude judging. Token totals include memory preparation calls and answering
prompt/completion usage, preferring recorded provider request ledgers so retries
are counted. Retrieved context is already part of the answer prompt and is not
added again. Local embedding/reranking work has no provider-token usage to infer.
Missing usage on any request, including a failed request, makes complete totals
and their averages unavailable. Reported tokens on failed requests still count.
`token_usage.known_recorded_tokens` is a separately labelled lower bound, never
an estimate of the missing usage or currency cost. Coverage includes
`missing_request_count`, `missing_failed_request_count`, `request_count`,
`records_without_ledger`, `unknown_record_count`, and `usage_complete`. Missing
legacy ledgers limit knowledge of unrecorded attempts even when an aggregate is
available. Conflicting duplicate ingestion measurements invalidate both complete
and known subtotals instead of arbitrarily choosing a cost.

Overall `token_usage` includes memory, answer, and combined complete totals,
coverage, and the recorded question denominator. Lifecycle subtotals use the same
semantics for memory, answering, and judging, with a separate
`known_recorded_provider_tokens` lower bound. Judging is excluded from headline
memory-plus-answering totals and included in lifecycle totals. Recorded rebuilds
and retry history affect campaign totals; per-question construction shares depend
on the query workload, so these plots do not isolate batching cost.

`stored_text_bytes` remains the sum of current snapshots only. It is accompanied
by `storage_scope`, `storage_conversation_count`, `expected_conversation_count`,
and `storage_cohort_complete`. `latest_successful_storage` separately selects the
latest explicitly successful retained ingestion per selected conversation,
including previous builds, and exposes measured/expected conversation counts.
Missing or failed builds are not silently counted as final successful storage.
This storage excludes embeddings and runtime overhead.

Library analysis supplies the actual source filename. Derived `source_name` and
`warnings` flag a `windowed_summary_k=N` filename that disagrees with configured
`window_size`. Configuration governs interpretation. Analysis never renames or
writes the source file; explicit enrichment remains a separate user action.

The main Benchmark report also renders these qualifiers directly for live runs,
library imports, and local file imports. Its token breakdown shows separate
known memory-plus-answering and lifecycle lower bounds, missing failed/all
request counts, incomplete phase records, legacy phase records without ledgers,
and deduplicated ingestion-build counts. Conflicting duplicate builds invalidate
known subtotals. Memory details show current-snapshot and latest-successful
storage with selected-conversation coverage. Local filename warnings use the
actual imported filename, without modifying the original imported report or
requiring network access. Missing ledger history cannot establish zero failures.

**Context tokens/question** is a separate measure of the supplied conversation or
memory text only. It excludes the question, instructions, generated answer, and
memory preparation costs. It uses the fixed benchmark WordPiece tokenizer rather
than provider usage counts. Recorded `diagnostics.memory_context_tokens` are
preferred; missing counts can be derived from exact `supplied_context` text using
the pinned locally cached tokenizer with padding/truncation disabled. This makes
no model calls or downloads. Empty context is zero. Missing text or a missing
local tokenizer remains unavailable; whole-prompt usage and byte budgets are not
substitutes. Means require a count for each recorded question in the selected
group. Both context and memory-plus-answering metrics are independent chart-axis
choices, with separate coverage. Completed saved-run analysis and library views
derive these metrics without changing the original source/export snapshots.

Formation uses `ingestion.preparation_seconds` across current and previous builds.
New runs record module construction, writes, embeddings, summaries, fact extraction,
and flushes within this timer. Older reports fall back to `ingestion.total_seconds`,
which lacks separately unrecorded construction time. The narrower `write_seconds`
is not substituted. Memory-review pauses and judging are outside preparation.
Each ingestion ID counts once; records without IDs count separately. Conflicting
measurements invalidate the affected totals.

For category filtering, shared memory tokens and preparation time are divided
across all recorded cases in their conversation, including failed cases, before
filtering. Selected but unrecorded questions do not dilute the denominator.
Preparation without recorded cases is included in the overall numerator, even
though it cannot be allocated to a category. The time is also exposed in
`unallocated_formation_seconds`. Missing conversation identities prevent category
allocation but do not prevent a known overall total divided by question count.

Query components prefer `diagnostics.execution_retrieval_seconds` and
`execution_answer_seconds`, which accumulate recorded work across resumes.
Older exports fall back to `retrieval_seconds` and `answer_seconds` only when the
corresponding cumulative field is absent. Explicit unknown cumulative values
stay unknown. Failed attempts and provider retry waits are included in new
recordings; reusing a saved prediction adds no query time. Legacy exports may
omit earlier failed attempts. Judging is never estimated by subtracting from a
total. Original `diagnostics.total_seconds` and derived legacy question-time
fields retain their definitions.

Runtime uses finite nonnegative measurements; zero is valid. Totals remain unavailable if any
case lacks the required measurement. Coverage shows contributing / recorded
cases, separately from accuracy and selected-question counts.

Storage sums final UTF-8 stored text bytes across matching module memory
snapshots. Missing final text size can be derived from snapshot entries. A
missing snapshot or incomplete sizes do not imply zero; an explicit empty
snapshot can establish zero. Sizes exclude embeddings and runtime overhead and
are not total repository disk use. Storage coverage lists measured / total
snapshots.

## Charts and question-type comparison

One full-width scatter plot compares two numeric metrics. Independent **X axis**
and **Y axis** selectors each offer judged accuracy, mean answer + judge tokens
per question, stored text in KiB (1,024 bytes), and mean formation-inclusive
runtime per question in seconds, excluding judging. Defaults are tokens on x and accuracy on y. Selecting the same metric
for both axes is supported. There are no chart-order controls.

All numeric axes start at zero. Accuracy has a fixed maximum of 100%; other
metrics use 10%, 20%, or 30% headroom rounded to a readable scale. Limits use runs
with both measurements. An all-zero or unavailable series retains a positive
axis. Each measured run has one colored point at its actual x/y coordinates.
If either value is missing, omit that point and expose the run through an
**Unavailable** button below the graph. Zero remains a measured coordinate.
Coincident points retain their real coordinates; tooltips identify other runs
at the same coordinates, and every point remains keyboard-focusable. Run numbers
and colors use name order and remain stable across axes, filters, and table sorts.
The run/color legend sits inside the bordered chart card in a wrapping row above
the plotting area. Long filenames wrap without covering points or axes; each
redraw moves the same legend into the new card without duplicates.

SVG coordinates use CSS pixels without viewBox scaling: tick text is 11px and
axis labels 12px, inheriting the workspace body font. Chart headings use the same
16px Space Grotesk style as surrounding panel headings. Container resizing,
including desktop sidebar collapse, redraws coordinates without scaling fonts.
Axis titles and units are English. Compact tick labels use explicit `en-US`
formatting (K/M/B) regardless of browser locale; tooltips retain exact formatted
measurements.

The accuracy table independently defaults to name ascending. **Sort table by**
chooses one field: name, any of the five question-type accuracy columns, or judge
completion for the current filter. Selecting a new field replaces the previous
one, with no multi-column sorting. Metric selections default to descending and
name to ascending; **Table order** can reverse this. Only the active column has
an `aria-sort` direction and arrow. Missing values always remain last in either
direction; equal values keep their original name order. Sort choices remain
active through filtering and rerendering but reset on page reload.

Each of the four tables (accuracy, runtime, measurement coverage, and lifecycle)
has its own Copy format selector and Copy table button. Spreadsheet copies use
quoted tab-separated text, formatted-table copies include HTML plus a plain TSV
fallback, and Markdown copies escape cell text. Copies include column headers and
the currently displayed primary values in their displayed row order, with no
secondary small notes/counts or CSS sorting arrows. Values shown as Unavailable
stay distinct from zero. Copying does not change source data, selections, filters,
or sort order. Format choices survive page-local rerenders.

Empty tables disable copying. Pending copies disable their own controls and show
a spinner; completion and clipboard errors are announced beside the control.
Browsers without formatted clipboard support copy spreadsheet text and identify
the fallback. Clipboard denial does not report success. The operation runs only
from the user's Copy table action.

Hovering, focusing, or tapping a point shows a tooltip with the full filename,
module, both axis values/units, and the scope/coverage for each axis. Accuracy includes judged/selected
counts and judge completion; token and runtime tooltips include contributing
case counts and totals (unavailable for incomplete measurements). Runtime also
shows allocated formation, retrieval, and answering means, run-level formation
and combined totals, measured build counts, and unallocated formation. A visible
runtime breakdown table presents these components alongside the chart. Storage shows
bytes and measured/total snapshots and explicitly retains run-level scope.
Notes describe each measurement's denominator and exclusions. Zero and
unavailable results remain inspectable through their buttons without drawing a
fabricated zero measurement. Keyboard focus and touch also open the details. Tooltips stay
within the viewport and dismiss on pointer leave, blur, Escape, outside press,
scroll, resize, or a chart rerender; focused points retain details on pointer leave.

The question-type selector filters accuracy, tokens, runtime, and completion.
Storage remains a run-level value. The accuracy table shows every question type
at once, with judged / selected counts in each cell:

| Category | Label |
| --- | --- |
| 1 | Multi-hop |
| 2 | Temporal |
| 3 | Open-domain |
| 4 | Single-hop |
| 5 | Adversarial |

Empty states prompt selection. Narrow layouts stack charts and allow tables to
scroll. Matching questions, model settings, and protocols remains the user's
responsibility; the page does not enforce matched cohorts or calculate statistical
significance. Partial runs and differing measurement coverage can affect means.

## API contracts and failures

| Endpoint | Behavior |
| --- | --- |
| `GET /compare` | Render the comparison page |
| `GET /api/results` | List relative library JSON paths sorted by displayed filename |
| `GET /api/results/file?path=...&analysis=1` | Return `{report}` with computed analysis; no write |
| `GET /api/results/file?path=...&download=1` | Download the saved JSON as an attachment |
| `POST /api/results/import` | Multipart `file`, optional `action` (`ask`, `duplicate`, `replace`), and `replace_path` for replacement; new copies return 201 with `{path, report}`; replacement returns 200 with `{path, report, replaced: true}` |
| `POST /api/results/enrich` | JSON `{path}`; enrich/update a selected library file; return `{path, report}` |
| `POST /api/results/rename` | JSON `{path, name}`; rename in the same directory; return `{path, previous_path}`; name conflicts return 409 |
| `DELETE /api/results/file?path=...` | Delete a library JSON; return `{deleted}` |

Missing files and paths outside the resolved library root return 404. Invalid
result structures, invalid JSON, and unsupported upload filenames return 400;
oversized requests return 413. Import/update filesystem failures return 503.
Duplicate imports without a choice, or stale replacement targets, return 409
with `{error, conflicts: [relative paths], duplicate_name}` and make no write.
Skip is handled locally without another upload request. The UI asks separately
for every conflict, including repeated filenames within the same upload batch.
Upload/save/delete/download status reports successful files and individual errors. Library reads
without analysis retain the existing benchmark report contract.

## Source and verification

[ResultAnalysis.py](../../src/ResultAnalysis.py), [app.py](../../src/app.py),
[compare.html](../../src/compare.html), [compare.js](../../src/compare.js), and
[compare.css](../../src/compare.css) implement the feature. Common navigation,
design ownership, and sources are documented in the
[shared workspace shell](workspace_shell.md).

| Latest implementation evidence (2026-11-02) | Scope |
| --- | --- |
| Full 143-test offline suite, Python 3.12.10 | Final tree after filename/dialog edge fixes; all tests passed, with JavaScript syntax checks also passing |
| 15 targeted result tests, Python 3.12.10 | Enrichment/preservation, persistence, names/duplicates, separate JSON downloads, rename/delete, invalid paths/names, and a real Windows junction sentinel |
| Comparison/import DOM suites, included in the result checks | Selection, filters, axes, zero/missing values, tooltips, single-field sorting, stable identities, duplicate choices, named benchmark export, source preservation and error/cancel handling |
| 14 frontend state tests | Shared workspace regression coverage for chat, inspection, settings and saved-run recovery/resume |
| Headless Chrome at 1440px and 390px | Shared sidebars/fonts/collapse/drawer; empty/selected library, sorted graphs, tooltip/touch/focus, file dialogs, named export/enrichment, and individual downloads; no horizontal overflow or JavaScript exceptions observed |

The implementation above was committed and pushed to `origin/main` as `8035e9b`.
The nine added result reports were also covered by a passing 10-test result-
analysis run before the push. This later Markdown-only review records the commit
and existing verification; it does not claim a fresh application test run.

Tests used temporary fixtures for file writes and no provider calls. Browser smoke
checks are not a comprehensive accessibility, screen-reader, cross-browser, or
scientific acceptance review. The final double-check repeated shared-shell,
sorting, rename/upload/delete, separate-download, and imported/saved benchmark
export flows using temporary fixtures, including source-preservation and metric
derivation checks. The 143-test run supersedes the earlier gap in full-suite
validation; the 138-test run remains historical.

[Analysis/API tests](../../tests/test_result_analysis.py),
[library/path tests](../../tests/test_result_library.py),
[comparison DOM tests](../../tests/test_compare_ui.js),
[benchmark import/export tests](../../tests/test_result_import.js), and
[frontend state tests](../../tests/test_frontend_state.js) provide source evidence.
Historical milestones are in [progress](../../PROGRESS.md); current changes and
remaining limits are summarized in [updates](../../UPDATES.md). The subsequent
documentation reconciliation checked contracts and links without rerunning
application tests; the later final double-check reran the full offline suite and
key browser flows. No real-model/provider or comprehensive accessibility review
is implied.


### Local dot-plot verification (2026-11-02)

The later approved single-plot change passed the 156-test offline suite,
including comparison DOM and 16 frontend-state tests, plus JavaScript syntax
checks. Headless Chrome at 1440px/390px verified one plot, all four metric choices,
keyboard-focus tooltips, and no horizontal page overflow using temporary synthetic
results. Desktop/phone screenshots were visually reviewed. The earlier 143-test
and committed-update evidence above describes the prior version. These newer
changes remain local and uncommitted.


### Configurable scatter revision (2026-11-02)

Supersedes the single-metric dot-plot design above. The affected 15-test result
suite and expanded comparison DOM checks passed. Isolated headless Chrome at
1440px/390px checked all 16 x/y combinations, confirmed stable 11px inherited
tick text and matching panel headings, exercised missing/coincident-run tooltips,
and verified bounded points without horizontal overflow. Screenshots were
visually reviewed. This revision used temporary fixtures and no provider calls;
the earlier 156-test full-suite evidence predates this chart-only revision.
