# Product experience development plan

Status: core features implemented; remaining study/acceptance work is partial or
unverified. Original source review: 2026-10-08. Compare/shared-shell/export and
documentation status reconciled: 2026-11-02.

First recorded: 2026-10-05, commit `acb7a6f`. Exact proposal approval, work start,
and full acceptance dates are unknown. The [archived proposal](archive/product_plan.md)
preserves the original requirements and phase sequence. This page supersedes its
"planning only" status; current contracts are in [spec/](../spec/README.md).

## Objective and dependencies

Provide distinct Home, Chat, LoCoMo Benchmark, and Compare Runs workspaces,
inspectable memory, direct QA with separate judging, and interpretable exported reports. Evaluation
depends on the memory interface and benchmark lifecycle; report/inspection UI
depends on the recorded diagnostics. The [UI plan](ui_refinement.md) handles
presentation, and the [comparison plan](controlled_comparison.md) handles study design.

## Original phases reconciled

| Phase | Current status/evidence | Timing |
| --- | --- | --- |
| 1. Product/evaluator decisions | Partial: routes, single-condition runs, direct QA, rubric, and persistence are implemented; a complete pinned-upstream scoring audit is not established | Plan recorded 2026-10-05; remaining audit unscheduled |
| 2. Navigation/page structure | Implemented: Home and three workspaces; shared sidebar template/script, active navigation, desktop collapse, mobile drawer | Compare added 2026-10-30; unified shell browser-checked 2026-11-02 |
| 3. Evaluation protocol | Implemented scoring/versions/review exchange; completed human calibration is not established | Present at review; calibration unscheduled |
| 4. Backend evaluation | Implemented: direct answer, separate judge, failure accounting, cancellation, saved results/resume | Present at review; exact phase completion unknown |
| 5. Report and inspector | Core reporting/inspection, named enriched export to Compare, managed result files, sorting/tooltips implemented; stratified sampling remains proposed | Refined and verified 2026-11-02; sampling unscheduled |
| 6. Documentation/acceptance | Repository documentation reconciled; scoped desktop/phone checks passed; comprehensive semantic/accessibility acceptance remains open | Documentation audit 2026-11-02; remaining acceptance unscheduled |

"Present at review" is evidence of implemented source, not a claimed completion
date or a fresh test result. The initial product commit was later extended; this
plan does not assign all current functionality to that one commit.

## Resolved historical choices

- Root is Home; Chat, Benchmark, and Compare Runs have distinct routes.
- Each chat/run selects one architecture; Compare Runs compares exported runs.
- Each valid answer is judged separately. Binary correctness is distinct from
  the 0-to-2 diagnostic rubric.
- Human review is export/import based; the current export includes all available
  predictions rather than stratified sampling.
- Benchmark runs persist and can resume. Chat memory remains process-local.

## Remaining sequence and acceptance

1. **Evaluator audit (unscheduled):** pin the upstream evaluator revision and
   compare local category handling using representative cases. Record deviations;
   do not silently rename local metrics as exact upstream equivalence.
2. **Human calibration (after audit; unscheduled):** select cases across categories,
   score bands, conditions, and uncertainty; collect ratings and inspect agreement,
   false positives, and false negatives. Existing review import/export supports
   labels but does not prove calibration has occurred. Preserve reviewed data and
   judge prompt version before publishing dependability claims.
3. **Comparison tooling (implemented/refined through 2026-11-02; scoped review passed):**
   `/compare` manages named JSON results, per-file duplicate choices, rename/delete,
   selected-only individual downloads, enrichment, sortable charts/table, tooltips,
   filters, and coverage. Benchmark reports save named comparison copies through
   the same restricted API. Shared-shell, desktop/phone, and key interaction checks
   passed in headless Chrome after the built-in browser sandbox failed. The final
   full offline suite passed 143 tests; earlier scoped checks passed 15 result
   tests and 14 frontend state tests. The implementation is committed on `main`
   as `8035e9b`; no new application test run is claimed for this Markdown update.
   Comprehensive accessibility/cross-browser acceptance, automatic matched-cohort/
   configuration-difference analysis, and stratified review sampling remain open.
4. **Acceptance review (after the selected scope; unscheduled):** inspect representative
   category, failure, partial-report, and resumed-run cases; record observations
   and dated evidence. Do not mark the entire original plan complete from source
   presence alone.

Existing [window hybrids](../spec/memory/window_hybrid.md) and
[long-term hybrids](../spec/memory/hybrid.md) are implemented; they are not newly
enabled by this documentation pass. New architectures and comparative studies
remain separately scoped, with no assigned date.

## Current specifications and evidence

[Chat](../spec/frontend/chat.md), [benchmark workspace](../spec/frontend/benchmark.md),
[Compare Runs](../spec/frontend/compare_runs.md),
[inspector](../spec/frontend/memory_inspector.md),
[evaluation](../spec/benchmark/evaluation.md), and
[results/resume](../spec/benchmark/results_and_resume.md) define current behavior.
[app.py](../src/app.py), [Benchmark.py](../src/Benchmark.py), and
[workspace.js](../src/workspace.js) are the implementation evidence.
Relevant existing tests include [binary scoring](../tests/test_binary_benchmark.py),
[lifecycle](../tests/test_benchmark_lifecycle.py), and
[frontend state](../tests/test_frontend_state.py). Their existence is not a record
of a paid comparison or manual acceptance study.
The 2026-10-30 run additionally verified [result analysis/API behavior](../tests/test_result_analysis.py)
and [comparison chart interactions](../tests/test_compare_ui.js).
Current behavior and verification scope are summarized in [updates](../UPDATES.md).
The [shared-shell spec](../spec/frontend/workspace_shell.md) owns common navigation;
the [documentation review](documentation_review.md) records the reconciled files.
