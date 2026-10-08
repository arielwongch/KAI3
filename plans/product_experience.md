# Product experience development plan

Status: core features implemented; remaining study/acceptance work is partial or
unverified. Reviewed against source on 2026-10-08.

First recorded: 2026-10-05, commit `acb7a6f`. Exact proposal approval, work start,
and full acceptance dates are unknown. The [archived proposal](archive/product_plan.md)
preserves the original requirements and phase sequence. This page supersedes its
"planning only" status; current contracts are in [spec/](../spec/README.md).

## Objective and dependencies

Provide distinct Home, Chat, and LoCoMo Benchmark workspaces, inspectable memory,
direct QA with separate judging, and interpretable exported reports. Evaluation
depends on the memory interface and benchmark lifecycle; report/inspection UI
depends on the recorded diagnostics. The [UI plan](ui_refinement.md) handles
presentation, and the [comparison plan](controlled_comparison.md) handles study design.

## Original phases reconciled

| Phase | Current status/evidence | Timing |
| --- | --- | --- |
| 1. Product/evaluator decisions | Partial: routes, single-condition runs, direct QA, rubric, and persistence are implemented; a complete pinned-upstream scoring audit is not established | Plan recorded 2026-10-05; remaining audit unscheduled |
| 2. Navigation/page structure | Implemented: `/`, `/chat`, `/benchmark` in `app.py`; separate workspaces in HTML/JS | Present at 2026-10-08 source review; exact phase completion unknown |
| 3. Evaluation protocol | Implemented scoring/versions/review exchange; completed human calibration is not established | Present at review; calibration unscheduled |
| 4. Backend evaluation | Implemented: direct answer, separate judge, failure accounting, cancellation, saved results/resume | Present at review; exact phase completion unknown |
| 5. Report and inspector | Core reports, filters, exports, and inspection implemented; dedicated cross-run comparison and stratified review sampling remain unimplemented proposals | Present at review; additional tools unscheduled |
| 6. Documentation/acceptance | Component documentation reorganized 2026-10-08; comprehensive manual semantic/visual acceptance is unverified | Documentation review dated; acceptance unscheduled |

"Present at review" is evidence of implemented source, not a claimed completion
date or a fresh test result. The initial product commit was later extended; this
plan does not assign all current functionality to that one commit.

## Resolved historical choices

- Root is Home; Chat and Benchmark have distinct routes.
- Each chat/run selects one architecture; benchmark conditions are now six.
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
3. **Comparison tooling (proposed; unscheduled):** decide whether a dedicated
   cross-run view and stratified sample selector are needed. If implemented, show
   configuration differences and denominators, preserving source exports.
4. **Acceptance review (after the selected scope; unscheduled):** inspect representative
   category, failure, partial-report, and resumed-run cases; record observations
   and dated evidence. Do not mark the entire original plan complete from source
   presence alone.

Future hybrid architectures remain independent module proposals with no assigned
date. They are not enabled by this documentation change.

## Current specifications and evidence

[Chat](../spec/frontend/chat.md), [benchmark workspace](../spec/frontend/benchmark.md),
[inspector](../spec/frontend/memory_inspector.md),
[evaluation](../spec/benchmark/evaluation.md), and
[results/resume](../spec/benchmark/results_and_resume.md) define current behavior.
[app.py](../src/app.py), [Benchmark.py](../src/Benchmark.py), and
[workspace.js](../src/workspace.js) are the implementation evidence.
Relevant existing tests include [binary scoring](../tests/test_binary_benchmark.py),
[lifecycle](../tests/test_benchmark_lifecycle.py), and
[frontend state](../tests/test_frontend_state.py). Their existence is not a record
of a paid comparison or manual acceptance study.
