# Compare Runs workspace

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

The report's derived `comparison` object is recomputed with `version: 1`,
`added_fields` (paths of filled fields, retained across repeated enrichment),
`definitions`, and `rows`. Each row contains `module`, `overall`, and `categories`
keyed by category string. Groups expose:

- `case_count`, `selected_count`, and `judged_count`;
- `accuracy_percent`, `completion_percent`, and `success_percent`;
- `mean_question_tokens`, `total_question_tokens`, and `token_count`;
- `mean_question_seconds`, `total_question_seconds`, and `runtime_count`.

Overall groups additionally expose `stored_text_bytes`, `storage_count`, and
`memory_count`. Existing scores, schema/protocol identifiers, predictions, and
evidence remain unchanged; the comparison object has its own version.

## Metric meaning and coverage

Judged cases have saved binary `correct` values of zero or one. Judged accuracy
is `100 × correct / judged`. Completion is `100 × judged / selected`; success is
`100 × correct / selected`. A nonempty question manifest supplies selected counts,
including unattempted questions. Without one, exported case counts are the
explicit fallback; they do not establish the original selection or failure-aware
benchmark denominator. A zero denominator produces an unavailable percentage.

Question tokens are answer plus judge provider tokens, excluding ingestion.
The mean includes only cases with both counts. Runtime uses recorded
`diagnostics.total_seconds`, including question retrieval, answering, and judging,
and excludes ingestion. Runtime means use only recorded finite values. Totals
remain unavailable if any case lacks the required measurement. Coverage counts
show the number of contributing cases.

Storage sums final UTF-8 stored text bytes across matching module memory
snapshots. Missing final text size can be derived from snapshot entries. A
missing snapshot or incomplete sizes do not imply zero; an explicit empty
snapshot can establish zero. Sizes exclude embeddings and runtime overhead and
are not total repository disk use. Storage coverage lists measured / total
snapshots.

## Charts and question-type comparison

Four horizontal bar charts show judged accuracy, mean tokens per question,
stored text in KiB (1,024 bytes), and mean runtime per question in seconds.
All numeric axes start at zero. Accuracy has a fixed maximum of 100%; the other
axes use the largest displayed value plus 10%, 20%, or 30% headroom, rounded up
to a readable scale. An all-zero or unavailable series retains a positive axis.
Bars have consistent run colors and exact value labels; missing values display
**Unavailable**. A color legend maps run numbers to full filenames and modules;
these also appear in the table. Short run labels and larger chart text on phones
keep charts readable. Library and comparison empty states explain the next step.

Charts default to name order. **Sort charts by** selects one shared field: name,
judged accuracy, mean tokens, stored memory text, or mean runtime. All four charts
use that ordering. **Chart order** selects ascending/descending. Accuracy defaults
to descending when chosen; name and resource metrics default to ascending.
Sorting uses the active question-type metrics; storage remains run-level.
Run numbers and colors are assigned from name order and stay consistent across
sort fields, chart rows, the legend, tooltips, and the accuracy table.

The accuracy table independently defaults to name ascending. **Sort table by**
chooses one field: name, any of the five question-type accuracy columns, or judge
completion for the current filter. Selecting a new field replaces the previous
one, with no multi-column sorting. Metric selections default to descending and
name to ascending; **Table order** can reverse this. Only the active column has
an `aria-sort` direction and arrow. Missing values always remain last in either
direction; equal values keep their original name order. Sort choices remain
active through filtering and rerendering but reset on page reload.

Hovering a bar or its row shows a tooltip with the full filename, module, graph
value and units, and question-type scope. Accuracy includes judged/selected
counts and judge completion; token and runtime tooltips include contributing
case counts and totals (unavailable for incomplete measurements); storage shows
bytes and measured/total snapshots and explicitly retains run-level scope.
Notes describe each measurement's denominator and exclusions. Zero and
unavailable results remain inspectable through their row without drawing a
misleading bar. Keyboard focus and touch also open the details. Tooltips stay
within the viewport and dismiss on pointer leave, blur, Escape, outside press,
scroll, resize, or a chart rerender; focused rows retain details on pointer leave.

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
