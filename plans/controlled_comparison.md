# Controlled LoCoMo comparison development and experiment plan

Status: v3 protocol implemented; completion of a matched six-condition experiment
and its scientific review is not established. Source review date: 2026-10-08.

First recorded: 2026-10-06, commit `c84cb77`. The old design states implementation
on 2026-10-06; that is preserved as a historical claim, not a fresh acceptance
result. Exact implementation start, deployment, and experiment completion dates
are unknown. The [archived design](archive/controlled_comparison_design.md) retains
the full original requirements, examples, and acceptance sequence.

## Objective and dependencies

Compare recency, summary, original-turn retrieval, and temporal facts under a
shared memory-context allowance, with question-only/full-context references.
Equal allowance does not equalize stored information, generation quality, or cost.
The protocol depends on module candidates, a fixed tokenizer, versioned fact
provenance, and manifest-based accounting. It extends the
[product/evaluation work](product_experience.md); UI presentation is separate.

## Implementation phases reconciled

| Phase | Current status/evidence | Timing |
| --- | --- | --- |
| 1. Conditions/config/manifest | Implemented: six explicit conditions, legacy normalization, full selected manifest | Recorded design 2026-10-06; source checked 2026-10-08 |
| 2. Tokenizer/candidate packing | Implemented: pinned counting, first-k whole-record packing, independent capacity, summary caps | Present at review; exact phase completion unknown |
| 3. Temporal history/provenance | Implemented: versions, validated sources, status labels, atomic writes, eviction | Present at review; exact phase completion unknown |
| 4. Failure-aware accounting | Implemented: judged accuracy, completion, end-to-end success, evidence coverage | Present at review; exact phase completion unknown |
| 5. UI/export/resume compatibility | Implemented capabilities, schema-v2 reporting and compatibility checks | Present at review; comprehensive acceptance run not claimed |
| 6. Matched benchmark study | Not verified complete; legacy saved runs do not establish matching selection/protocol | Unscheduled |

Summary batching is already implemented and defaults to 20 session-bounded turns.
Its exact introduction date was not isolated in this review. Per-turn construction
remains selectable via runner options with `summary_batch_size=1`. The historical
design's treatment of batching as a future experiment has been superseded; batch
size remains an experimental variable and must be recorded.

## Next experiment sequence and timing

1. **Freeze selection/settings (unscheduled):** choose identical conversations,
   categories, ordered question manifests, answer/judge settings, and protocol.
   Primary proposed setting: B=2,000 for the four memory conditions; k=null for
   window/vector/facts; window capacity 10; unlimited vector/fact versions. Select
   and record summary batch size explicitly. Baselines retain their exemptions.
2. **Validate before model calls (after configuration):** run relevant mocked
   protocol, semantic-memory, batching, recovery, report/import, and frontend
   checks. Inspect invalid counts, oversized records, tokenizer failure, historical
   fact status, provenance, and selected-question denominators. Review exported
   identities to ensure resume cannot mix incompatible runs.
3. **Execute matched runs (after validation; unscheduled):** run each condition
   separately with the frozen selection. Save full configuration, context, failure,
   usage, storage, and identity records. Do not compare an old 100-question full
   context run against differently selected new runs as a matched experiment.
4. **Resolve/review outcomes (after runs):** retry eligible failed work without
   relabelling reused predictions as newly ingested context. Complete appropriate
   human review/calibration; report unresolved cases, completion, and metric bases.
5. **Publish comparison (after review; unscheduled):** compare accuracy and evidence
   coverage alongside ingestion/retrieval cost, storage limits, and failures.
   Label fact coverage as a provenance proxy and results from partial runs as
   provisional. No monetary estimator is assumed.

These are dependency stages, not scheduled calendar commitments. This documentation
task does not run a paid experiment or establish that existing results are matched.

## Deferred proposals

| Proposal | Dependency / reason for separate experiment | Timing |
| --- | --- | --- |
| Budget, finite-k, and finite-storage sweeps | Establish a labelled reference configuration first | Unscheduled |
| Summary batch-size sweep | Hold selection/model/allowance fixed; record construction policy | Unscheduled |
| Vector neighboring-turn expansion | New retrieval policy and evidence/accounting validation | Unscheduled |
| Attributed summaries | Implement validated source attribution before reporting source coverage | Unscheduled |
| Current-only versus temporal facts | Separate condition/protocol label; preserve historical interpretation | Unscheduled |
| Hybrid memory | Independent architecture and acceptance scope | Unscheduled |
| Monetary cost estimator | Dated provider prices and separate answer/judge/ingestion accounting | Unscheduled |

## Current specifications and acceptance evidence

[Lifecycle](../spec/benchmark/lifecycle.md), [baselines](../spec/benchmark/baselines.md),
[context budget](../spec/benchmark/context_budget.md),
[evaluation](../spec/benchmark/evaluation.md), and
[results/resume](../spec/benchmark/results_and_resume.md) own the implemented contract.
[Temporal facts](../spec/memory/temporal_fact_store.md) owns version operations.

Existing acceptance coverage is in [controlled comparison tests](../tests/test_controlled_comparison.py),
[semantic memory tests](../tests/test_semantic_memory.py),
[summary tests](../tests/test_summary_benchmark.py), and
[recovery tests](../tests/test_benchmark_recovery.py), with frontend/report tests
linked by the feature specs. These tests verify mechanics using mocks; they do not
establish real-model extraction accuracy, calibration, or completed experimental runs.
