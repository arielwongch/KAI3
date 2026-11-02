# Standalone reranker confirmation contract

Prepared 2026-11-03. Status: ready for protocol review, not frozen or executed.
Requires actual [human calibration](../spec/benchmark/adjudication.md), a sealed
sample-size/power decision, and separate approval for provider execution/spending.
The exploratory 100-question cohort is excluded from confirmatory selection.

## Matched conditions

- One original-turn corpus and identical frozen embedding state per conversation.
  Save logical snapshot and embedded-state hashes before either condition.
- Baseline: cosine top50 then top10 in cosine order. Treatment: the identical
  cosine top50, cross-encoder reranking, then top10. Verify pool IDs/order match.
- Both arms: B=2,000, whole-record packing, identical tokenizer artifact, answer
  prompts/settings, judge settings, completion/retry rules, and no QA writeback.
- Pin embedding/tokenizer revisions and cross-encoder
  `cross-encoder/ms-marco-MiniLM-L6-v2` revision
  `233902d25c440f23af6f7d6e94d2946bac0bee0a`; capture the scoring policy, dependency
  versions, actual source hashes, code revision, hardware, cache state, requested
  and returned provider model identities. Unavailable immutable provider identity
  is a stated limitation, not an invented value.
- Reuse actual frozen states. Existing job resume rebuilds ingestion and is not
  proof that the same embedded state was reused. Before execution, demonstrate a
  runner/state-loading path and verify hashes; adapter work requires review if
  the current runner cannot meet this requirement.

## Seal before observing new outcomes

Freeze unused question identities from `data/locomo/locomo10.json`, the dataset
hash, categories including category-5 abstention, eligibility, seed, allocation,
sample size/power rationale, repetitions, timing order, retry rules, scoring and
analysis script. Histories have already been seen; this is new-question validation,
not new-user generalization. Do not quietly replace failed or ambiguous cases.

Proposed analysis for review: three answer repetitions per question/condition,
paired condition order randomized with seed 20261103. Use identical retry policy
(maximum five attempts) and retain every attempted request and unresolved outcome.
Human correctness is binary and independently reviewed; report ambiguity and
reviewer agreement. Apply calibration findings before sealing evaluator settings.
Measure evidence-ID completeness separately from reviewer-assessed sufficiency.

Co-primary endpoints: paired packed evidence-ID completeness difference and paired
calibrated correctness difference, with questions averaged across repetitions.
Report the same fixed selected-question denominator, completion, and unresolved
outcomes; provide observed-label accuracy separately rather than silently dropping
failures. Preserve evidence/review uncertainty explicitly.

Proposed uncertainty method: paired conversation-cluster bootstrap, 50,000
resamples, seed 20261103, resampling conversations and retaining all paired
questions/repetitions within each. Use two-sided 95% percentile intervals for
both endpoints. Require both lower bounds to exceed zero to claim improvement.
Only ten conversations are available; freeze a power/sensitivity analysis and
state this cluster limitation before spending. If power is inadequate, retain
baseline or report insufficient evidence. Do not tune intervals after outcomes.

## Required outputs and execution gates

Store the signed-off manifest/analysis hash and frozen settings before running.
Report pool, final selection, and packed completeness; human correctness;
completion and failures; p50/p95 retrieval and end-to-end latency; repeated-answer
stability; ingestion/query/provider usage and measurement coverage. Count shared
ingestion once per state and show construction cost separately. Missing usage is
unknown. Record deviations and all failures, including interrupted attempts.
Gold evidence is diagnostic only and must never influence retrieval or packing.

Execution is gated on human calibration, frozen states/identities, local model
availability, a reviewed analysis script, and an authorized provider spending
limit. No paid run is initiated by this contract. Confirmation does not validate
shared reranking of facts/hybrids or periodic extraction. Subsequent Delta studies
must reuse the exact same summary and vector states across component controls.
