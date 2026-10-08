# UI refinement development plan

Status: core redesign implemented; complete visual/accessibility acceptance is
unverified. Source review date: 2026-10-08.

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
| 5. Responsive/accessibility consolidation | Responsive CSS and keyboard interactions exist; comprehensive accessibility/obsolete-style audit unverified | Remaining audit unscheduled |
| 6. Documentation and visual acceptance | Feature specs updated 2026-10-08; full viewport/state review not established | Documentation reviewed; visual acceptance unscheduled |

## Remaining work and when it happens

1. **Acceptance scope (unscheduled):** choose desktop/narrow viewport sizes and
   keyboard/accessibility checks. Include empty chat, lost server memory, loading,
   successful/failed sends, benchmark setup, review pause, partial/failed/completed
   reports, imported legacy reports, and long inspector records.
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
Implementation: [index.html](../src/index.html), [workspace.js](../src/workspace.js),
and [style.css](../src/style.css). Existing [frontend state tests](../tests/test_frontend_state.py)
and [result import tests](../tests/test_result_import.py) check behavior, not full
visual or accessibility acceptance. No new screenshot review is claimed here.
