# Development plans and history

Original status review: 2026-10-08. Latest Compare/shared-shell/export, local setup,
recovery, and documentation reconciliation: 2026-11-02.
Current behavior is documented under
[spec/](../spec/README.md). This directory owns implementation sequences,
outstanding work, dependencies, and dated history.
Use [updates](../UPDATES.md) for current changes, [progress](../PROGRESS.md) for
implementation evidence, and the [documentation review](documentation_review.md)
for the complete Markdown audit and retained historical material.

## Plan register

| Plan | First recorded in Git | Status as of review | Next work and timing |
| --- | --- | --- | --- |
| [Product experience](product_experience.md) | 2026-10-05 (`acb7a6f`) | Shared workspaces, managed result library, and named benchmark-to-Compare export implemented; calibration/study acceptance incomplete | Evaluator audit, human calibration, and remaining acceptance; unscheduled |
| [UI refinement](ui_refinement.md) | 2026-10-05 (`acb7a6f`) | Shared shell and Compare refinements implemented; scoped desktop/phone browser checks passed | Comprehensive keyboard/screen-reader/cross-browser and unreviewed states; unscheduled |
| [Controlled comparison](controlled_comparison.md) | 2026-10-06 (`c84cb77`) | Protocol implemented; completion of a matched study not established | Choose matched configuration, validate, then run study; unscheduled |
| [Documentation review](documentation_review.md) | Working-tree audit, 2026-11-02 | Complete inventory, affected docs reconciled, archived contracts preserved | Keep in sync with future feature changes |

No new feature implementation or benchmark execution is scheduled by this
documentation reorganization. Proposed items below remain proposals, not active
tasks. Exact proposal/approval dates and deployment dates are unknown unless
explicitly recorded. "Implemented" means repository code exists; it does not mean
every acceptance review or experiment has been completed.

## Recorded sequence

| Recorded date | Repository evidence | Meaning and limits |
| --- | --- | --- |
| 2026-09-15 | `df2e17f`, original `PROGRESS.md` | Initial Phase 1 outline first appears |
| 2026-09-21 | `1b0a2da`, `22c3cac` | Memory plug-in interface and first frontend changes recorded |
| 2026-10-04 | `2ab25a0` | Vector/current-fact implementation changes recorded |
| 2026-10-05 | `f97777c`, `acb7a6f` | LoCoMo/frontend work and product/UI plan files recorded |
| 2026-10-06 | `c84cb77` | Benchmark update and controlled-comparison design recorded |
| 2026-10-08 | Current documentation review | Component specs separated from plans; statuses reconciled against source |
| 2026-10-30 | Compare Runs working-tree implementation and 134 passing offline tests | Local uploads/enrichment, cross-run charts, and question-type comparisons implemented; browser visual acceptance unverified |
| 2026-11-02 | Local setup/recovery working-tree changes and 33 passing targeted offline tests; follow-up Python 3.12.10 setup verification | PowerShell/environment guidance, snapshot validation and warnings, preserved merge-conflict variants, and removal of runtime files from Git tracking; new `venv`, dependency consistency, two recovery tests, and four-page HTTP startup verified on Python 3.12 |
| 2026-11-02 | Compare refinements and shared shell; latest 15 result tests, 14 frontend state tests, and scoped headless Chrome checks | Shared-folder naming/duplicates/rename/delete, selected JSON downloads, sorting/tooltips, named enriched benchmark export, folder guards, and shared navigation verified; full accessibility and matched-study acceptance remain open |
| 2026-11-02 | Repository-wide Markdown reconciliation | Updates log, canonical shared-shell spec, cross-links, status/evidence corrections, and per-file audit; no application behavior changed by this documentation pass |
| 2026-11-02 | Final double-check: 143 offline tests passed after edge fixes; fresh headless Chrome flows | Filename/dialog regressions, shared shell, sorting, separate downloads and both saved/imported named exports verified; source reports preserved; broad accessibility/scientific acceptance still separate |

Commit references use dates from local Git history, not inferred feature start,
completion, or release dates. The 2026-10-08 row records this documentation work
and does not claim a new application release or Git commit.
The 2026-10-30 and 2026-11-02 rows record working-tree implementation and
verification, not releases or committed milestones. The initial 33-test recovery
run used Python 3.11.3; the follow-up checked basic setup/startup and two recovery
tests under Python 3.12.10. Those recovery/setup checks did not rerun the full suite.
The 138-test run preceded the final UI refinements; later scoped checks passed
15 result tests plus 14 frontend state tests. The final double-check then passed
all 143 offline tests after edge-case fixes and repeated key browser checks.
See [project progress](../PROGRESS.md),
[local setup](../spec/local_setup.md), and
[saved-run recovery](../spec/benchmark/results_and_resume.md) for details.

## Status and timing convention

Every maintained plan records first-known history, current review date, phase
status, dependencies/sequence, remaining acceptance work, and timing. Use
`implemented`, `partial`, `proposed`, `superseded`, or `unverified` as appropriate.
Unscheduled work explicitly says `unscheduled`; uncertain historical dates stay
unknown. Specification check dates describe source review, not implementation dates.

When a phase is implemented, update its component/feature spec, record supporting
commit/date evidence here, and leave any remaining experiment or acceptance work
open. Do not present a proposal as current behavior merely because it appears in
an old plan. Do not overwrite archived wording with present-day claims.

## Historical records

- [Initial Phase 1 outline](archive/initial_phase.md)
- [Product proposal](archive/product_plan.md)
- [UI refinement proposal](archive/ui_refinement_plan.md)
- [Controlled-comparison design and implementation sequence](archive/controlled_comparison_design.md)

Archived documents retain original requirements, risks, and open questions.
Their notice explains why old "planning only" or "current state" paragraphs
may differ from today's source. Maintained plan pages below resolve that distinction.
