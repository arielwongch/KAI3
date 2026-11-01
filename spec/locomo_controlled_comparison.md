# Controlled LoCoMo comparison (split by feature)

Current protocol v3 specifications:

- [Lifecycle, ingestion, and configuration](benchmark/lifecycle.md)
- [Question-only and full-context baselines](benchmark/baselines.md)
- [Context budget and packing](benchmark/context_budget.md)
- [Evaluation and evidence coverage](benchmark/evaluation.md)
- [Results, persistence, and resume](benchmark/results_and_resume.md)
- [Temporal fact component](memory/temporal_fact_store.md)

For the implemented result-comparison UI, see [Compare Runs](frontend/compare_runs.md),
including named benchmark exports, enrichment, sorting, and measurement coverage.
This tool does not establish that independently loaded reports form a matched study.

Implementation phases, dated history, outstanding experiments, and deferred work
are maintained in the [controlled-comparison plan](../plans/controlled_comparison.md).
The [historical design](../plans/archive/controlled_comparison_design.md) preserves
the original proposal. This file remains only as a navigation pointer.
