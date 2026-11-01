# Documentation reconciliation — 2026-11-02

Status: complete. Scope: the Compare/result-library, benchmark export, shared
workspace design, and related setup/progress changes in the current working tree.
This records a documentation review, not a release or a fresh application test run.

## Method and ownership

Inventory all repository Markdown, including hidden paths while excluding Git and
ignored virtual/runtime directories. Search for Compare, result-library paths,
uploads, downloads/ZIPs, sidebar/navigation, exports, test counts, dates, and
acceptance claims. Reconcile affected guides/specs/plans against implementation
and the verification already performed. Preserve archival proposals and unaffected
memory/protocol contracts. Check local Markdown file/heading links and inventory
coverage after editing. No source code, user results, environment files, or
archived proposal bodies were changed by this pass.

Current contracts live in the [specification index](../spec/README.md);
[updates](../UPDATES.md) summarize behavior and verification;
[progress](../PROGRESS.md) retains dated implementation evidence. Earlier ZIP,
UUID-folder, upload-only deletion, and blocked-browser descriptions in progress
are explicitly historical. The initial audit recorded 15 result tests, 14 frontend
state tests, and scoped headless Chrome checks. A subsequent final double-check
passed all 143 offline tests after edge-case fixes and repeated key browser flows;
the earlier 138-test run remains historical. Full accessibility/scientific
acceptance remains open.

## Complete Markdown inventory

Initial inventory: **35** Markdown files. Final inventory: **38** files: **16 updated**, **3 added**, and **19 reviewed and retained**. Every file is listed below.

| File | Outcome | Reason |
| --- | --- | --- |
| [plans/archive/controlled_comparison_design.md](../plans/archive/controlled_comparison_design.md) | Reviewed; retained | Historical proposal/phase wording and existing archival notice preserved |
| [plans/archive/initial_phase.md](../plans/archive/initial_phase.md) | Reviewed; retained | Historical proposal/phase wording and existing archival notice preserved |
| [plans/archive/product_plan.md](../plans/archive/product_plan.md) | Reviewed; retained | Historical proposal/phase wording and existing archival notice preserved |
| [plans/archive/ui_refinement_plan.md](../plans/archive/ui_refinement_plan.md) | Reviewed; retained | Historical proposal/phase wording and existing archival notice preserved |
| [plans/controlled_comparison.md](../plans/controlled_comparison.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [plans/documentation_review.md](../plans/documentation_review.md) | Added | Updates log, shared-shell owner, or this complete audit |
| [plans/product_experience.md](../plans/product_experience.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [plans/README.md](../plans/README.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [plans/ui_refinement.md](../plans/ui_refinement.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [PROGRESS.md](../PROGRESS.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [README.md](../README.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/benchmark/baselines.md](../spec/benchmark/baselines.md) | Reviewed; retained | Protocol, baselines, packing and execution semantics unchanged |
| [spec/benchmark/context_budget.md](../spec/benchmark/context_budget.md) | Reviewed; retained | Protocol, baselines, packing and execution semantics unchanged |
| [spec/benchmark/evaluation.md](../spec/benchmark/evaluation.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/benchmark/lifecycle.md](../spec/benchmark/lifecycle.md) | Reviewed; retained | Protocol, baselines, packing and execution semantics unchanged |
| [spec/benchmark/results_and_resume.md](../spec/benchmark/results_and_resume.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/frontend.md](../spec/frontend.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/frontend/benchmark.md](../spec/frontend/benchmark.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/frontend/chat.md](../spec/frontend/chat.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/frontend/compare_runs.md](../spec/frontend/compare_runs.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/frontend/memory_inspector.md](../spec/frontend/memory_inspector.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/frontend/workspace_shell.md](../spec/frontend/workspace_shell.md) | Added | Updates log, shared-shell owner, or this complete audit |
| [spec/local_setup.md](../spec/local_setup.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/locomo_controlled_comparison.md](../spec/locomo_controlled_comparison.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/locomo_memory_modules.md](../spec/locomo_memory_modules.md) | Reviewed; retained | Existing memory-spec navigation pointer still resolves to the canonical owner |
| [spec/memory/fact_store.md](../spec/memory/fact_store.md) | Reviewed; retained | Memory algorithm/snapshot contract unchanged by the UI/library work |
| [spec/memory/hybrid.md](../spec/memory/hybrid.md) | Reviewed; retained | Memory algorithm/snapshot contract unchanged by the UI/library work |
| [spec/memory/interface.md](../spec/memory/interface.md) | Reviewed; retained | Memory algorithm/snapshot contract unchanged by the UI/library work |
| [spec/memory/no_memory.md](../spec/memory/no_memory.md) | Reviewed; retained | Memory algorithm/snapshot contract unchanged by the UI/library work |
| [spec/memory/sliding_window.md](../spec/memory/sliding_window.md) | Reviewed; retained | Memory algorithm/snapshot contract unchanged by the UI/library work |
| [spec/memory/summarization.md](../spec/memory/summarization.md) | Reviewed; retained | Memory algorithm/snapshot contract unchanged by the UI/library work |
| [spec/memory/temporal_fact_store.md](../spec/memory/temporal_fact_store.md) | Reviewed; retained | Memory algorithm/snapshot contract unchanged by the UI/library work |
| [spec/memory/vector_store.md](../spec/memory/vector_store.md) | Reviewed; retained | Memory algorithm/snapshot contract unchanged by the UI/library work |
| [spec/memory/vector_store_reranker.md](../spec/memory/vector_store_reranker.md) | Reviewed; retained | Memory algorithm/snapshot contract unchanged by the UI/library work |
| [spec/memory/window_hybrid.md](../spec/memory/window_hybrid.md) | Reviewed; retained | Memory algorithm/snapshot contract unchanged by the UI/library work |
| [spec/README.md](../spec/README.md) | Updated | Current feature contracts, cross-links, evidence, dates or superseded claims reconciled |
| [spec/shared_memory_interface.md](../spec/shared_memory_interface.md) | Reviewed; retained | Existing memory-spec navigation pointer still resolves to the canonical owner |
| [UPDATES.md](../UPDATES.md) | Added | Updates log, shared-shell owner, or this complete audit |

## Validation

The documentation-only checks verify local file/heading links, complete inventory
coverage, duplicate headings, stale current-contract descriptions, and whitespace.
Final results: **38 inventory rows**, **397 local file/heading links checked**,
**0 broken links**, **0 missing inventory entries**, **0 duplicate heading IDs**,
and a passing `git diff --check`. The inventory was also cross-checked with
`git ls-files` so tracked documents and new working-tree documents are included.
The final stale-contract scan found superseded behavior only in explicitly
historical entries or statements explaining the current separate-download behavior.
Application/model/browser tests were not rerun for prose-only edits. Archived
status wording and old component review dates are retained deliberately; current
feature changes do not imply a fresh review of unrelated memory/protocol code.
The later user-requested double-check reran the full 143-test offline suite and
browser flows, fixed small filename/dialog edge cases, and updated current
verification claims. The initial documentation-only audit counts above remain
the record of that earlier pass.
