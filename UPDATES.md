# Updates

## Saved benchmark deletion - 2026-11-02

Added **Delete** to Test Benchmark's Saved runs entries, with a run-specific
confirmation. Deletion removes the saved result, original dataset copy, worker
log, and control/lease files to free local space. Exported Compare Runs and
downloaded JSON copies are kept. Active runs must be cancelled and stopped first;
finishing threads and held worker leases also block deletion.

Successful deletion refreshes the sidebar and clears the deleted run's open
report/selection. Failed file cleanup keeps the snapshot and listed run for
retry. The new DELETE endpoint shares the registry lock with resume/cancel/review
mutations and uses an exact file list without recursive folder deletion.

Verification: **164 offline tests passed**, including eight deletion API/storage
tests and 20 frontend-state tests. JavaScript syntax and whitespace checks passed.
Isolated desktop/phone Chrome checks at 1440px/390px exercised confirm/cancel,
active guards, actual fixture cleanup, and report reset; dialog screenshots were
visually reviewed. Only temporary synthetic runs were deleted. Changes are local
and uncommitted.


## Local approved implementation - 2026-11-02

These changes are local and uncommitted; the earlier main-branch update below
remains historical.

- Added **Windowed Summary** (`windowed_summarization`) and **Windowed Fact Store**
  (`windowed_fact_store`), preserving the existing architectures. One k controls
  both the recent window and updates from each k incoming entries. Defaults are
  10 chat exchanges / 100 benchmark speaker messages. Batches span sessions;
  benchmarks flush the remainder before memory review and QA.
- Fact batches use one extraction call with multiple changes. Current facts keep
  paired user/assistant context and batch provenance. Benchmark facts apply
  per-turn operations chronologically, retaining historical versions and validated
  speaker/source attribution. Failed extraction/embedding rolls back the batch.
- Reused the pinned reranker for all embedding-based retrieval except standalone
  Vector Store: current/historical facts, Beta/Gamma long-term stores, paired
  hybrid components, and Windowed Fact Store. Candidate pool defaults to 50 per
  store, separately configurable from final retrieval k; paired hybrids support
  component overrides. Snapshots/traces expose model identity and both score types.
- Replaced the four simultaneous bar charts with **one full-width scatter plot**.
  Independent x/y selectors offer accuracy, tokens, storage, or runtime, defaulting
  to x = tokens per question and y = accuracy. Graph text matches the surrounding
  workspace without SVG font scaling. Axis ticks use English K/M/B abbreviations
  regardless of browser locale. Colors, filters, coverage, focus/touch
  tooltips, zero/missing handling, and independent table sorting remain available.
- Updated chat/API/CLI/benchmark settings and resume compatibility. Incompatible
  earlier cosine-only runs require a new run; matching standalone reranker runs
  remain eligible. Existing result exports were not rewritten.

Verification: the full **156-test offline suite** passed on Python 3.12.10,
including 13 new memory/integration tests, comparison DOM checks, and 16 frontend
state tests. JavaScript syntax and diff whitespace checks passed. Isolated
headless Chrome at **1440px and 390px** verified the plot choices, focus tooltips,
new-mode settings, and absence of page overflow; screenshots were visually
reviewed. Browser fixtures were temporary, and model/provider calls were mocked.
Real-provider extraction and matched benchmark experiments remain unverified.

The subsequent configurable-axis/typography revision passed the affected
**15-test result suite** and expanded comparison DOM checks. Headless Chrome
at 1440px/390px checked all 16 axis combinations, matching heading/body fonts,
missing/coincident-point tooltips, and no overflow. The full 156-test result
above predates this chart-only revision.

Contracts: [periodic memory](spec/memory/periodic_window.md),
[shared reranking](spec/memory/vector_store_reranker.md), and
[Compare Runs](spec/frontend/compare_runs.md).

## Main branch update — 2026-11-02

Implemented changes were committed and pushed to `origin/main` as
`8035e9bb0026211c7dff1bc3cc2a97e1fd804b67` — **Add managed run comparisons and
unify workspace UI**. This records a main-branch update, not a tagged release or
deployment. [Progress](PROGRESS.md) records implementation history;
[specifications](spec/README.md) define current contracts;
[plans](plans/README.md) track remaining work.

### Compare Runs and result files

- New uploads save directly to `data/result/` with original filenames, including
  parentheses, spaces, Unicode, and extension case. Older nested uploads remain
  usable. Previously sanitized names require re-upload to recover their names.
- Every duplicate filename gets its own Skip / Keep both / Replace choice.
  Keep both uses the first available `(1)`, `(2)`, etc. Replacement targets are
  explicit when multiple older copies share a name.
- Existing and uploaded results share Rename and confirmed Delete actions.
  Rename keeps the parent folder and bytes and rejects name conflicts.
- **Download selected** is the only download control and saves separate JSON
  files. Browsers may request permission for multiple downloads.
- Library refresh sorts by filename. One shared chart field orders all four
  graphs; the accuracy table independently defaults to name and accepts one
  category-accuracy/completion field at a time. Direction is selectable; missing
  values stay last. Run numbers/colors remain consistent across sort changes.
- Bar tooltips show the filename, module, value, scope, and relevant coverage or
  totals; keyboard focus and mobile touch expose the same details.
- The commit includes nine additional benchmark result exports and derived
  `comparison` data for six existing reports. Original fields in those six
  reports are unchanged. These files do not establish a matched benchmark study.

### Benchmark export and shared design

- Benchmark reports offer **Export to Compare Runs**, with an editable filename,
  duplicate handling, and **Open Compare Runs** after saving. Saved jobs supply
  their full export snapshot; imported reports supply a copy of the original JSON.
- The shared enrichment path fills calculable missing token/storage fields and
  recomputes comparison metrics without model calls. Missing labels/timings are
  not inferred; source reports and normal Export JSON behavior are preserved.
- Chat, Test Benchmark, and Compare Runs use a shared sidebar template and
  navigation script. Compare adopts the workspace fonts, header, colors, cards,
  controls, dialogs, and internal scrolling. Desktop collapse and the mobile
  drawer include active navigation, dismissal, and focus handling.

### Folder boundary and local operation

Library operations accept JSON paths only inside the configured `data/result/`
root. They reject traversal, absolute/drive paths, unsafe names, symlinks, and
Windows junctions. Rename cannot move files to another folder. Mutations share a
lock and enrichment uses atomic saves. These are API folder guards, not OS-level
isolation or a multi-user authentication system.

Windows setup and damaged saved-run recovery were also documented/verified on
this date; see [local setup](spec/local_setup.md) and
[recovery](spec/benchmark/results_and_resume.md#snapshot-validation-and-damaged-file-recovery).

### Verification and outstanding work

The final double-check passed the **full 143-test offline suite** on Python
3.12.10 after the final fixes, including result/API, comparison/import DOM,
frontend-state, and recovery coverage. JavaScript syntax checks also passed.
The earlier scoped checks passed 15 result tests and 14 frontend state tests.
Headless Chrome rechecked
desktop (1440px) and phone (390px) layouts, all three sidebars, sort/tooltip/file
actions, named benchmark export, derived metrics, and separate downloads against
temporary fixtures. No user result files or provider calls were used for those
browser checks. The saved-run export was additionally exercised through the real
benchmark export endpoint using a synthetic job; both saved and imported sources
remained unchanged. An actual Windows junction test preserved an external sentinel.

The earlier **138-test full offline run** remains historical evidence; the
143-test run above supersedes the previous gap in final-tree validation. Review
also fixed malformed-Unicode filename validation, prevented duplicate suffixes
from bypassing the filename byte limit, and protected reopened rename dialogs
from queued close events. Regression assertions cover those edge cases.
Comprehensive accessibility acceptance, real-provider/model validation, human calibration, and
a matched benchmark study remain outstanding. The documentation-only
reconciliation did not rerun application tests; the later double-check did.

The [documentation review](plans/documentation_review.md) inventories every
Markdown file, updates affected guides/specs/plans, preserves archived history,
and records the link and stale-contract checks.

### Post-commit documentation recheck

Rechecked all 38 Markdown files after the push. Updated affected guides, progress,
plans, and verification sections to identify commit `8035e9b` and distinguish
the final 143-test run from earlier targeted evidence. Historical archive text
and unaffected memory/protocol contracts were retained. This follow-up changes
Markdown only; application tests were not rerun for the prose changes.
Before the push, the 10-test result-analysis suite passed again with the added
reports, and result parsing and credential-pattern checks passed.
