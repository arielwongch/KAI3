# Updates

## Unreleased — 2026-11-02

These are working-tree changes, not a published release. [Progress](PROGRESS.md)
records implementation history; [specifications](spec/README.md) define current
contracts; [plans](plans/README.md) track remaining work.

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
Comprehensive
accessibility acceptance, real-provider/model validation, human calibration, and
a matched benchmark study remain outstanding. The documentation-only
reconciliation did not rerun application tests; the later double-check did.

The [documentation review](plans/documentation_review.md) inventories every
Markdown file, updates affected guides/specs/plans, preserves archived history,
and records the link and stale-contract checks.
