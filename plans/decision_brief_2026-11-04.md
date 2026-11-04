# Decision brief validation and follow-up — 4 November 2026

Status: independently checked against local history, saved exports, current
working files, review artifacts, and the two linked research sources. Accounting
and reporting corrections are implemented locally. Actual human calibration and
new provider-backed experiments remain pending. Original saved exports and the
user-supplied brief are preserved.

## Decision

Retain actual blinded human adjudication as the next research step. Qualify
campaign usage and storage coverage before comparing architectures. The periodic
summary runs establish execution, not an isolated benefit from batching or a
statistically established architecture winner. Do not expand memory complexity
or treat the local windowed-fact repair as effectiveness evidence.

## Verified evidence and qualifications

The local default-branch history has four commits between `443238f` and
`bb3c46a51643bc9297562ff8450111f1c13954ce`. Local source and result history verify
the implementation claims. Remote GitHub issue/PR counts were not rechecked;
the brief's empty-queue statement remains unverified in this review.

Recomputing the three periodic-summary exports reproduces their scores,
context counts, manifest/settings identities, and recorded usage subtotals:

| Configured window/update interval | Correct / selected | Mean context tokens | Known recorded memory + answer tokens, lower bound | Recorded missing-usage failures, memory + answer | Ingestion builds | Current conversation snapshots |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 36 / 100 | 2,000 | 3,652,720 | 1 | 10 | 10 / 10 |
| 20 | 34 / 100 | 2,000 | 2,508,183 | 20 | 15 | 3 / 10 |
| 50, filename says 100 | 35 / 100 | 1,998.9 | 1,188,234 | 3 | 10 | 10 / 10 |

For window 50 there are also two judge failures with missing usage, giving five
across all phases. Judging is excluded from the table's token subtotal. Missing
usage means complete provider-token totals are unknown in all three runs.
The lower bounds are not monetary costs or controlled batching-cost estimates.

The reports match on dataset/manifest hashes, answer/judge prompt hashes and
settings, pinned tokenizer identity, packing identity, and the 2,000-token
allowance. Categories are 41 multi-hop, 43 temporal, 14 open-domain, and two
single-hop questions; category-5 adversarial/abstention questions are absent.
Selection is the first ten questions in each of ten conversations.

The interval-20 report retains enough previous successful ingestion records to
recover storage for all ten selected conversations: 123,303 UTF-8 text bytes.
This is a separate measure from its three current snapshots. Comparable latest
successful-ingestion text totals are 106,608 bytes for window 10 and 178,409 for
window 50. These exclude embeddings/runtime overhead and do not isolate summary
quality or batching effects. Window size changes retention and cadence together,
and summaries were independently generated.

Vector-k10 and reranker-50-to-10 exports are identical to `443238f` after removing
the derived `comparison` object. Refreshed charts therefore are not new model
experiments. The exploratory 30/100 versus 47/100 automated success result is
unchanged, with calibration still required.

The review packet has 42 question cases and 84 response slots. The label template
has no completed human labels; the retained pending calibration report records
zero human labels and a zero calibration denominator. Mock tests, this code
review, and automated judgments cannot supply actual blinded adjudication.

The brief's historical test count is not current working-tree validation.
Current tests are run separately and recorded in the implementation update.
The local windowed-fact failure investigation and repair also postdate the
reviewed commit: all 100 questions in that saved run were ingestion-blocked;
the repair has offline validation, not a successful new provider-backed run.

## Confirmed defects and implemented corrections

1. **Missing failed usage became zero.** Both `ResultAnalysis.phase_tokens` and
   the live-report JavaScript ignored error requests without usage. Complete
   totals now remain unavailable when any required request usage is missing.
   Separate known recorded lower bounds preserve measurable work, including
   reported tokens on failed requests. Coverage distinguishes missing failed
   requests, other missing requests, legacy ledgers, and incomplete records.
   Headline scope excludes judging; lifecycle scope includes it. Conflicting
   repeated ingestion IDs invalidate subtotals instead of choosing a value.
2. **Filename identity could mislead selection.** Analysis of a library file
   checks its actual filename against configured periodic-summary window size
   and exposes a warning. Configuration is authoritative. No export is renamed
   or rewritten merely by viewing analysis.
3. **Current snapshots looked like all-conversation final storage.** Derived
   metadata and chart text now identify current-snapshot scope and selected
   conversation coverage. Latest explicitly successful retained ingestion
   storage is a separate measure, including eligible previous builds. Missing
   conversation storage stays unavailable.
4. **The follow-up plan described superseded packing and query-only cost.**
   The plan now describes reserved recall, recent admission, tiny-budget
   fallback, summary fitting, and formation-inclusive accounting. Current versus
   historical correction answer quality still requires a separate evaluation.

The derived comparison schema is version 6. Historical result bytes, predictions,
labels, request ledgers, and filenames are not changed by this validation.

## Research validation

[Chain on Demand, v1](https://arxiv.org/html/2611.02480v1) supports the brief's
description: the paired allocator comparison holds raw memory, candidates,
reconstruction, reader, and judge fixed. Its setup uses 200 candidates, 60
anchors, same-session neighbors, and GPT-4o-mini as reader/judge. The authors
explicitly disclose overlap between the development diagnostic and the reported
LoCoMo evaluation. This is a useful hypothesis source; it does not transfer
headline scores or establish effectiveness under KAI3's budget and evaluator.

[Top-k Retrieval Leaves Memory Value Undetermined, abstract](https://arxiv.org/abs/2611.03289)
matches the brief's abstract-level screening and 2 November submission date.
Its identification claims concern memory contributions under retrieval logs;
this review does not independently reproduce them. Keep attribution changes
deferred and use controlled interventions for KAI3 decisions.

## Remaining plan and acceptance

1. **Actual human calibration.** Have reviewers complete the existing blinded
   packet with reviewer provenance. Preserve source automated labels. Report
   priority and agreement-sample denominators separately, reviewer disagreement,
   ambiguity, unresolved cases, and whether judge/reference repair must precede
   confirmation. Keep stages unknown where historical traces are insufficient.
2. **Freeze standalone reranker confirmation after calibration.** Follow the
   [confirmation contract](reranker_confirmation.md): identical frozen raw turns,
   embeddings and cosine top50 pool; cosine top10 versus reranked top10;
   B=2,000; matched prompts/settings/retries/packing. Freeze unused questions,
   category-5 coverage, repetitions, sample-size rationale, paired cluster
   analysis, completion/usage coverage, and positive-interval acceptance before
   observing new outcomes. Provider execution remains a separate future step.
3. **Isolate periodic factors afterward.** Freeze retention, update cadence,
   packing, summaries/state identities, and query workload independently. Count
   shared construction once and campaign retries/rebuilds separately. A coupled
   window sweep cannot attribute a cost or correctness change to batching alone.
4. **Validate current/historical correction behavior separately.** Include
   oversized evidence, omitted recent corrections, old/new assertion questions,
   and fixed-budget completeness. Packing regression tests are implementation
   checks; model answer quality is an experimental outcome.

Acceptance for this local follow-up is correct unknown-usage propagation,
explicit lower bounds and coverage, non-mutating artifact warnings, accurate
storage scope, repeatable tests, and reconciled plans. No human-label completion,
architecture effectiveness claim, or provider experiment is implied.

Verification completed: all 242 offline Python tests, 30 workspace frontend
checks, and the comparison UI checks passed. Six dedicated uncertainty tests
cover missing/reported failed usage, phase separation, conflicting ledgers,
partial storage cohorts, actual filename warnings, and non-mutating analysis.
The full suite caught an upload/source-name consistency defect and an obsolete
import expectation; both were corrected before the passing full rerun.
`git diff --check` passed and `data/result` has no diff.

Reporting completion: the main live/imported Benchmark report now displays the
same lower-bound, missing-usage, rebuild, and storage-cohort qualifiers directly.
Local-file imports flag actual filename/config mismatches without a server round
trip or source mutation. The remaining research steps above are unchanged.
Final reporting checks passed: 30 frontend state tests, import/export regressions
and the Python wrapper, comparison UI tests, and all three saved periodic-summary
exports through the import/export path. Documentation and whitespace checks are
complete; saved result bytes remain unchanged.
