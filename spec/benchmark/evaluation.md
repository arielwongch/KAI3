# LoCoMo scoring and evidence evaluation

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

## Purpose and inputs

Evaluation consumes a question, its reference, a saved prediction, and the exact
supplied context after answering. Gold references and annotated dialogue evidence
are not inputs to memory construction or retrieval. Results distinguish semantic
correctness, lexical overlap, source coverage, and operational completion.

## Case state and aggregation

The manifest contains every selected question before ingestion, keyed by condition,
sample ID, and question index. Each selected case has exactly one accounting state:

| State | Meaning |
| --- | --- |
| `judged_correct` | Valid judge result with binary correctness 1 |
| `judged_incorrect` | Valid judge result with binary correctness 0 |
| `judge_failed` | Prediction exists but judging failed |
| `answer_failed` | Answer generation/context processing failed without a valid prediction, outside the separately classified states |
| `context_limit_exceeded` | Whole-request guard rejected the request |
| `ingestion_blocked` | Memory ingestion failed before this question could be answered |
| `not_attempted` | No completed outcome yet, including pending/cancelled work |

Outcome counts sum to `selected_count`, overall and per category. Retries update
the same case rather than multiplying the denominator.

```text
judged_accuracy = correct_count / judged_count
completion_rate = judged_count / selected_count
end_to_end_success_rate = correct_count / selected_count
accuracy_bounds = [correct_count / selected_count,
                   (selected_count - judged_incorrect_count) / selected_count]
```

Use null when a displayed denominator is zero. The manifest aggregator creates
rows for nonempty selected groups; no selected questions means no such rows.
Unresolved questions lower operational success, without claiming their answers
are semantically incorrect. Bounds are accounting bounds, not confidence intervals.
Active/interrupted run summaries remain provisional. For example, 90 correct and
10 judge failures yield 100% judged accuracy, 90% judge completion, and 90%
end-to-end success. Legacy `accuracy` is retained with its saved interpretation.

## Lexical scoring

`normalize` lowercases, removes commas/punctuation and the words `a`, `an`, `the`,
and `and`, then splits whitespace. F1 applies Porter stemming to normalized
tokens and counts multiset overlap. The project category-aware `qa_score` has
the following behavior; it is not relabelled as exact match:

| Category | Project QA score behavior |
| --- | --- |
| 1 (multi-hop) | Split reference/prediction on commas; average each reference item's best prediction F1 |
| 2 (temporal) | F1 against the reference text |
| 3 (open-domain) | F1 against the reference text before the first semicolon |
| 4 (single-hop) | F1 against the reference text |
| 5 (adversarial) | 1 when prediction includes `no information available` or `not mentioned`; otherwise 0 |

Complementary `exact_match` compares normalized token lists and `token_f1` uses
the best accepted variant. Category 1 variants are comma-separated reference
items; category 3 uses text before the first semicolon. Category 5 uses abstention
phrase matching, also accepting `cannot determine` and `unable to answer` for
these complementary metrics. These heuristics are separate from the judge's
semantic decision. This specification describes local code, not a claim of exact
compatibility with every upstream LoCoMo evaluator revision.

## Judge flow and stored result

Each valid prediction receives a separate DeepSeek judge call. The payload has
`question`, `reference_answer`, `prediction`, and supplied `evidence`; it omits
the memory condition name. Category 5 uses a null reference. The prompt requires
binary semantic equivalence to the reference independently of context availability,
all requested facts, no contradictions/inventions, and appropriate abstention.

The JSON result requires integer `correct` (0 or 1); integer `correctness`,
`completeness`, `support`, `abstention`, and `overall` (0 to 2); a string `rationale`;
and boolean `uncertain`. Judge model/prompt identifiers, prompt hashes, usage,
timing, and responses are recorded. Invalid judge output is a judge failure;
the prediction and deterministic scores remain available. Saved prediction reuse
on resume is defined in [results and resume](results_and_resume.md).

## Evidence coverage

For nonempty unique annotated dialogue evidence E, let R be the union of source
IDs of fully supplied records:

```text
evidence_recall = |E intersect R| / |E|
evidence_complete = E is a subset of R
```

Window/vector/full-context use original turn IDs and basis `original_turn`.
Temporal facts use validated assertion `source_ids` and basis
`fact_source_provenance`. Summary/question-only have no applicable coverage;
empty evidence gives null, not zero. Retraction/transition sources do not
automatically count as support for the old assertion. Fact provenance coverage
does not prove extraction preserved every annotated detail. Conditional accuracy
for complete/incomplete evidence groups includes their denominators and is
diagnostic association rather than causal attribution.

## Human review and limitations

Review export supplies all available predictions with case indices, references,
evidence, and judge results. It is not an implemented stratified sampler. Review
import requires all four 0-to-2 rubric ratings and a valid case index, accepts
optional notes, and is blocked while a run is active. Exact judge/human agreement
is reported by dimension with sample counts. Unreviewed reports say uncalibrated;
having a review workflow does not establish that calibration has been performed.

Provider failures, imperfect judge/extractor behavior, and small reviewed samples
limit interpretation. Missing usage or unavailable metrics stay null. Monetary
cost estimates are not fabricated. Remaining calibration work belongs to the
[product plan](../../plans/product_experience.md).

## Source and verification

[Benchmark.py](../../src/Benchmark.py) owns scoring/accounting and
[app.py](../../src/app.py) owns review endpoints.
[Binary benchmark tests](../../tests/test_binary_benchmark.py),
[controlled comparison tests](../../tests/test_controlled_comparison.py), and
[audit regression tests](../../tests/test_audit_regressions.py) cover scoring,
denominators, provenance, and failure paths.
