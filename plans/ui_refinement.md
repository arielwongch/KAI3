# UI refinement development plan

Status: core redesign implemented; complete visual/accessibility acceptance is
unverified. Original source review: 2026-10-08. Shared-shell/Compare/export status
and documentation update: 2026-11-02; scoped browser checks passed on that date.

First recorded: 2026-10-05, commit `acb7a6f`. Exact design approval, implementation
start, and final acceptance dates are unknown. The [archived proposal](archive/ui_refinement_plan.md)
retains the original design direction and acceptance checklist. Its "planning only"
status and old four-tile benchmark proposal are historical, not current UI behavior.

## Objective and dependencies

Separate setup, execution, and report views; make memory inspection and chat state
readable; retain charcoal/lime styling. UI work depends on existing lifecycle,
evaluation, and snapshot contracts and must preserve their semantics. It follows
the [product plan](product_experience.md); protocol changes have their own
[comparison plan](controlled_comparison.md).

## Phase status and sequence

| Original phase | Current status/evidence | Timing |
| --- | --- | --- |
| 1. Visual direction | Dark theme and compact cards/tables implemented; explicit design sign-off date unknown | Plan recorded 2026-10-05 |
| 2. Setup/running/results states | Implemented in `index.html`/`workspace.js` | Present at 2026-10-08 review; exact completion unknown |
| 3. Summary/category/question report | Core cards, category breakdown, filters, details, and review/import controls implemented | Present at review; exact completion unknown |
| 4. Chat and memory workspace | Architecture cards, session navigation, selected-mode state, composer, and full-height inspector implemented | Present at review; exact completion unknown |
| 5. Responsive/accessibility consolidation | Shared sidebar template/script, compact Compare styles, drawer dismissal/focus handling implemented and browser-checked | Focused checks 2026-11-02; comprehensive accessibility/style audit unscheduled |
| 6. Documentation and visual acceptance | Affected docs reconciled; 1440px/390px key states inspected; full viewport/state matrix not established | Documentation/browser evidence 2026-11-02; remaining acceptance unscheduled |

On 2026-10-30, `/compare` added a responsive result library, upload/save/download
controls, four comparison charts, adjustable axis headroom, question-type
filters, and coverage tables. DOM and API checks passed in the full 134-test
offline suite. Browser preview could not start because of a sandbox initialization
error. That initial limitation was superseded by scoped headless Chrome checks
on 2026-11-02, not by a comprehensive accessibility sign-off.

The current implementation uses the shared workspace shell on all three pages.
Compare supports original filenames, duplicate choices, same-folder rename,
confirmed deletion, selected-only separate JSON downloads, per-view single-field
sorting, stable run colors, coverage tooltips, and named enriched benchmark
exports. Browser checks covered desktop/phone library, charts, dialogs, exports,
downloads, and shared navigation; no JavaScript errors or horizontal overflow were
observed. The final double-check passed all 143 offline tests after small
filename/dialog edge fixes and repeated the key browser flows. Earlier scoped
checks passed 15 result tests plus 14 frontend state tests.
See [updates](../UPDATES.md#verification-and-outstanding-work) for limits.

## Remaining work and when it happens

1. **Remaining acceptance scope (unscheduled):** extend the completed 1440px/390px
   smoke checks into a comprehensive viewport/state and assistive-technology matrix.
   Choose additional desktop/narrow viewport sizes and
   keyboard/accessibility checks. Include empty chat, lost server memory, loading,
   successful/failed sends, benchmark setup, review pause, partial/failed/completed
   reports, imported legacy reports, and long inspector records. Include Compare
   Runs with no selection, multiple long filenames, upload/save failures, partial
   measurement coverage, all-zero/unavailable charts, question-type filters,
   axis headroom changes, and narrow layouts. Existing smoke coverage is recorded
   above; repeat it only after relevant changes, not as an unperformed task.
2. **Visual and interaction review (after scope; unscheduled):** verify scroll
   containment, readable labels, focus states, record selection, menu/file controls,
   and unavailable-versus-zero metrics. Record dated evidence rather than inferring
   success from screenshots or tests that were never run.
3. **Gap fixes (after review; unscheduled):** implement only identified issues and
   update the relevant feature spec. Proposed drag/drop upload, more granular
   disagreement/evidence filters, and mobile Back navigation require explicit
   verification or scoping; the old proposal is not proof they exist.
4. **Close acceptance (after fixes):** rerun relevant state tests and check affected
   visual states without changing scoring, memory behavior, or saved metrics.

## Current specifications and evidence

[Chat](../spec/frontend/chat.md), [benchmark](../spec/frontend/benchmark.md), and
[memory inspector](../spec/frontend/memory_inspector.md) own current interactions.
The [Compare Runs specification](../spec/frontend/compare_runs.md) owns the new
comparison interactions and their remaining acceptance limits.
Implementation: [index.html](../src/index.html), [workspace.js](../src/workspace.js),
and [style.css](../src/style.css), plus the
[shared shell](../spec/frontend/workspace_shell.md) and Compare-specific files.
Existing [frontend state tests](../tests/test_frontend_state.py)
and [result import tests](../tests/test_result_import.py) check behavior, not full
visual or accessibility acceptance. Dated headless browser screenshots were
inspected during implementation; this documentation pass did not rerun them.
