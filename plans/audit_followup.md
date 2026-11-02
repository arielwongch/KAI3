# External audit follow-up plan

First recorded and reviewed: 2026-11-02.
Status: proposed; implementation and experiments are unscheduled.
Scope: follow-up to the external decision brief for commit `d52eb6d` and its
independent verification against the current working tree.

## Decision and evidence

Prioritize correction retention, judge calibration, and a controlled reranker
confirmation. Defer new memory architectures and broad parameter sweeps until
these establish a trustworthy baseline.

Verification reproduced the saved vector/reranker results: 30 versus 47 confirmed
successes out of 100 selected questions, 28 versus 53 evidence-complete contexts,
18 improvements, one regression, and one unresolved reranker judgment. These are
automated labels, not adjudicated human correctness. Mean delivered context is
580.96 versus 594.01 benchmark tokens. All reports use the first ten questions
per conversation and contain no adversarial questions.

The current working tree includes periodic modes and shared reranking beyond the
audited commit. Existing exports do not validate those additions. The current
165-test offline suite passed during verification; browser/provider execution
was not repeated. Preserve existing uncommitted work and original exports.

## 1. Make recent-window admission explicit

Priority: high. Size: small to medium. Dependency: none.

Problem: `WindowHybridMemory.iter_context_candidates` supplies long-term records
before recent turns, and `MemoryContext.build_memory_context` packs greedily.
Verification reproduced an old statement surviving while a recent correction was
omitted, even though that correction fit alone.

Proposed policy for Alpha/Beta/Gamma and the two periodic window modes:

- Admit recent whole records newest first, counting headings and separators.
- Spend the remaining allowance on long-term records in retrieval order.
- Render selected recent records oldest to newest. Admission order and display
  order must be separate.
- Keep stored history intact. Apply correction precedence to current-state
  questions; make prompt guidance explicitly permit earlier statements when the
  question asks about a historical state.
- Record omissions by tier, including recent records too large to fit alone.
  Do not promise correction retention when the correction itself exceeds budget.

Files: `src/WindowHybridMemory.py`, `src/MemoryContext.py`, relevant prompt code
in `src/ReAct.py`, benchmark identity/resume code in `src/Benchmark.py`,
`tests/test_window_hybrid_memory.py`, and `tests/test_periodic_memory.py`.
Update the window/periodic memory and context-budget specifications.

Acceptance:

- A fitting latest correction survives competition from long-term records.
- Tight-budget tests cover multiple recent turns, oversized records, empty tiers,
  labels, and chronological rendering without storage mutation.
- Current-state and historical-state fixtures verify the selected evidence and
  prompt instructions; real answer correctness remains an experiment outcome.
- A distinct window packing identity participates in export and resume checks;
  older runs remain readable but cannot resume under changed semantics.
- Standalone memory packing behavior is preserved. Run affected tests and then
  the full offline suite.

## 2. Build an adjudication set before trusting judge gains

Priority: high. Size: medium. Dependency: existing reports only; independent of 1.

Add an offline review export/tool with stable dataset/sample/question identities.
Include the union of the 18 improvements, one regression, unresolved judgment,
and 16 evidence-complete reranker failures. Deduplicate cases, then add a seeded,
category-stratified sample of agreements. Record selected and total counts so an
oversampled error set is not presented as population accuracy.

Randomize condition labels and hide existing judge outcomes from human reviewers.
Provide the question, answer, reference, evidence, and source conversation needed
to resolve ambiguous references. Keep a separate key for subsequent comparison.
Use a second reviewer to resolve disagreements where available; otherwise report
the single-reviewer limitation. Do not overwrite original automated labels.

Record binary correctness, reference ambiguity, and failure stage: candidate
retrieval, reranking, packing, answering, judging, or unresolved. Mark stages
unknown when the original trace lacks the required candidate-pool evidence.
Investigate `conv-49`, question index 7, without treating a missing judge result
as an incorrect answer. Human labels require actual human review.

Files: proposed `tools/audit_results.py`, offline tests, and a review-output schema.
Keep generated review outputs separate from the source reports.

Acceptance: reproducible blinded packets, adjudicated labels with provenance,
explicit calibration denominators and disagreement counts, and a decision on
whether reference/judge problems need correction before confirmation.

## 3. Record enough provenance and lifecycle accounting

Priority: high. Size: medium. Dependency: define the confirmation contract first.

Extend exports additively with:

- Cosine candidate-pool IDs/ranks and pool evidence completeness, separate from
  final selected and packed evidence. Gold annotations remain diagnostic-only.
- Explicit answer and judge request settings, provider-returned model identity
  and fingerprint when available, code revision plus working-tree identity,
  embedding/tokenizer/reranker identities, and snapshot hashes. Distinguish
  requested model aliases from immutable versions; flag unavailable versions.
- Ingestion, retrieval, answer, and judge usage/time separately, plus lifecycle
  totals with coverage counts. Count ingestion once per built memory, with any
  amortization assumption stated. Unknown measurements remain unknown.
- CPU retrieval timings with warm/cold status and hardware context; report p50
  and p95. Keep provider usage tokens distinct from benchmark tokenizer counts.

Files: `src/Benchmark.py`, `src/Diagnostics.py`, `src/ResultAnalysis.py`, relevant
retrieval code, and results/evaluation specifications. Expose the minimum needed
in Compare Runs to label current token/runtime figures as query-only and make
lifecycle scope clear. A monetary estimator is optional; prices and currency must
be dated if introduced.

Acceptance: fixtures verify pool/packed distinctions, total accounting without
double counting, missing-data coverage, and safe import of legacy reports. No
new fields are invented for historical runs. Add a non-mutating metadata check
for filename/config discrepancies; preserve original filenames and bytes unless
renaming is requested separately.

## 4. Freeze and execute a held-out reranker confirmation

Priority: next experiment. Size: medium. Depends on 2 and 3; freeze code after 1
if that change is included in the tested revision.

Use standalone Vector Store for the baseline and Vector Store + Reranker for the
treatment. Existing 100 questions are exploratory only.

1. Before inspecting new outcomes, freeze unused question identities, categories,
   abstention cases, seed, sample size/power rationale, endpoints, repetitions,
   retry rules, and analysis script. Histories are already seen; describe this as
   new-question validation, not new-user generalization.
2. Freeze one source corpus and identical original-turn representations and
   embedding state. Baseline: cosine top50 then top10. Treatment: the identical
   cosine top50, pinned cross-encoder, then top10. Both use B=2,000 and identical
   tokenizer, packing, prompts, answer/judge settings, and storage policy.
3. Check matching manifests/settings and local model availability offline. Then
   execute answering/judging when provider access and an experiment spending
   limit have been agreed. This plan initiates no provider calls.
4. Report paired evidence-completeness and correctness differences, completion,
   unresolved outcomes, latency, usage, and repeated-answer stability. Use a
   prespecified paired analysis accounting for questions clustered within the
   ten conversations; report category counts and the limited number of clusters.

Acceptance: claim improvement only when the prespecified uncertainty intervals
for both primary differences exclude zero in the positive direction. Otherwise
retain the baseline or report insufficient evidence/power. Publish all frozen
conditions, failures, and deviations. A successful standalone result does not
validate reranking facts or every hybrid component.

## 5. Isolate Delta and validate expanded integrations

Priority: subsequent experiment. Size: medium. Depends on a trustworthy evaluator
and completion of 4; unscheduled.

Compare vector-only, summary-only, and Delta at the same allowance and with the
same questions/settings. Build and freeze one summary per conversation, reuse
that exact summary in summary-only and Delta, and preserve identical vector
state. Freeze component shares and retrieval limits. Attribute and report both
component construction and total lifecycle cost, including shared/reused costs.

The existing Delta k20/k50 summaries differ in all ten conversations, so their
50-to-51 success difference cannot isolate retrieval depth. Do not rerun that
sweep with newly generated summaries and call it a controlled depth comparison.

Evaluate the working-tree extensions separately: reranking of facts and hybrid
components, and periodic update modes, each against an explicit matched baseline.
Keep factual provenance coverage distinct from semantic completeness. Do not
claim combined summary evidence coverage without validated attribution.

Acceptance: repeatable held-out benefit with recorded cost and failure tradeoffs
before expanding recommended defaults. Keep operational mock-test acceptance
separate from model effectiveness.

## Sequence and completion

Implement 1 first; prepare 2 in parallel with the offline reporting work in 3.
Complete human calibration before spending on 4. Run 5 only after confirmation
provides a reliable reference. These are dependency stages, not calendar promises.
No architecture expansion, clustering, broad tuning sweep, or automatic rewrite
of historical result files is part of this follow-up.

This plan complements [controlled comparison](controlled_comparison.md); its
standalone reranker confirmation is the narrower next experiment. Keep the
broader six-condition study open until separately completed. Update the relevant
specifications and progress log when each implementation or experiment actually
passes its acceptance criteria.
