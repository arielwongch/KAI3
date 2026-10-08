# Development plans and history

Status review: 2026-10-08. Current behavior is documented under
[spec/](../spec/README.md). This directory owns implementation sequences,
outstanding work, dependencies, and dated history.

## Plan register

| Plan | First recorded in Git | Status as of review | Next work and timing |
| --- | --- | --- | --- |
| [Product experience](product_experience.md) | 2026-10-05 (`acb7a6f`) | Core features implemented; calibration/comparison acceptance incomplete or unverified | Audit and human evaluation before relying on comparative findings; unscheduled |
| [UI refinement](ui_refinement.md) | 2026-10-05 (`acb7a6f`) | Core layout implemented; visual/accessibility acceptance not established | Inspect desktop/narrow/error states after choosing a review scope; unscheduled |
| [Controlled comparison](controlled_comparison.md) | 2026-10-06 (`c84cb77`) | Protocol implemented; completion of a matched study not established | Choose matched configuration, validate, then run study; unscheduled |

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

These are Git commit dates from the local history, not inferred feature start,
completion, or release dates. The 2026-10-08 row records this documentation work
and does not claim a new application release or Git commit.

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
