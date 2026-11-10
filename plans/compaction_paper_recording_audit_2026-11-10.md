# Compaction papers: reported parameters versus KAI3 recordings

Review date: 2026-11-10, Asia/Hong_Kong. Research-only follow-up: no application
changes, experiments, result rewrites, commits or pushes.

## Scope and evidence standard

Read the experimental methods, relevant appendices and result definitions of four
primary papers, then checked actual local source and the existing recording
contract. Here, “reported” means stated in the paper; this does not establish that
the authors publicly release every per-request log. “Recorded in KAI3” means
present in the current implementation for **new runs**, not retroactively present
in old exports. Configurable, recorded, derivable and empirically tested are
different claims.

Stopped after the four papers covered recursive history compression, independent
compression controls, token-budget evaluation, evidence preservation, cost and
statistical comparison. Follow-up appendix reads clarified metric definitions and
protocol mismatches without adding another required recording category. This is a
targeted comparison, not an exhaustive literature review.

## What the papers actually report

| Paper and sections checked | Reported controls and measurements relevant to this audit | Implication for KAI3 |
| --- | --- | --- |
| [ACON v3](https://arxiv.org/html/2510.00615v3), §§4.1/4.5, Appendices B.2/B.3 | Separate history/observation thresholds; examples include history 4,096/2,048 tokens. Retains the latest action-observation pair. Specifies temperature 0, seed 42, model snapshots, prompts, optimization candidates/training selection. Reports steps, peak tokens, dependency and cost. | We record threshold, prompts, model/settings and compression events. We lack a recent-tail control, snapshot-pinned provider execution, ACON-defined trajectory metrics and prompt-optimization provenance. |
| [The Complexity Trap v3](https://arxiv.org/html/2508.21433v3), §3, Appendices A/C.1/D.2 | Separates summarized batch size N from raw tail M; main summary setting N=21, M=10. Reports task success, trajectory length, token/cache-sensitive costs and summary overhead. Uses paired bootstrap with 10,000 resamples and 95% intervals. | Our trigger and retained percentage are separate, but are different controls from N/M. We record usage/overhead; we do not implement this summary-with-tail policy or paired uncertainty analysis. |
| [LLMLingua-2 v2](https://arxiv.org/html/2403.12968v2), §5, Tables 1–5, Appendices A/I | Reports token budgets, realized tokens/compression factors, downstream task scores, compressor/reader identities, decoding and latency/hardware/memory measurements. Distinguishes question-aware and question-agnostic methods. Describes training hyperparameters for its learned compressor. | We have budget/count/outcome/request records, but use abstractive whole-memory compaction rather than its extractive learned model. No local compressor GPU-memory or FLOP measurement exists. Training parameters are inapplicable until we train a compressor. |
| [KEEP-Bench v1](https://arxiv.org/html/2610.26827v1), §4.1, Table 3, Appendices C.2/D | Reports sentence budgets, ICL/thinking/decoding, actual output lengths, source/output factor, proposition-level survival and All-Rec/Para-Rec/Cond-Rec. Documents its judge and validation. Its compressor receives the question. EPR is limited to models with FLOP estimates. | We archive source/output and judge settings, but do not score proposition survival. Its question-aware protocol must be a separate condition; do not introduce future QA into our memory formation. |

These papers do not establish an optimal KAI3 retained percentage or trigger.
Their reported thresholds, budgets, models, tokenizers and tasks differ from ours.

## Field-by-field comparison with current source

Status: **Yes** = explicitly recorded; **Partial** = a related field exists but
does not provide the same control/measurement; **Missing** = not implemented;
**N/A** = not meaningful for the present remote-API LoCoMo protocol.

| Parameter or measurement | KAI3 status | Actual owner/location | Gap or interpretation |
| --- | --- | --- | --- |
| Requested retained percentage | Yes | `config.retain_percent`; event `requested_retain_percent` | Percentage of current rendered memory, not the model context window. |
| Independent compaction trigger | Yes | `config.compaction_trigger_tokens`; event `reason`, `before_tokens` | Token threshold, not a turn-count batch size. |
| One-time/repeated mode and recursive depth | Yes | `config.compaction_mode`; event parent/depth; frozen source/replacement artifacts | Can inspect recursive operations; not evidence of retained facts. |
| Source cohort/order and omissions | Yes | `dataset_artifact`, `ordered-source`, `compaction_source_entries`, omission counters, dataset/question manifests | Comparisons can verify identical source and question cohorts. |
| Uncompressed reference | Yes, supported condition | `retain_percent=100` no-op; separate baseline modes | Must fit its declared reader budget. This is support, not an already-run comparison. |
| Raw recent tail M independent of compressed prefix | Partial | Current whole-window policy; all active entries are replaced | Effectively no protected tail. No compaction-specific `raw_tail_entries` knob; other architectures' `window_size` is not this control. |
| Turn batch N independent of tail | Missing in compaction | Existing token-trigger policy | Do not map `compaction_source_entries` to N: it limits one-time source scope, not update cadence. |
| Requested and actual token budget | Yes | Event `target_tokens`, `before_tokens`, `after_tokens`, `actual_retain_percent`; tokenizer identity | Full framing is counted by the declared renderer. |
| Aggregate compression factor | Partial, derivable | Raw event counts exist; Compare Runs exposes mean retained percentage | Add a named cohort-level factor if wanted; current mean is a different aggregation. |
| Peak sequence/context load | Partial | `peak_active_tokens`, source events, archived requests, provider usage | Peak counter covers committed active memory. It is not ACON's maximum trajectory sequence excluding system prompts, nor GPU/KV memory. |
| Compressor, reader, judge identities | Partial | Model/settings fields; request returned model/fingerprint; provider endpoint | Roles are recorded, but current execution uses a provider alias. A returned label is not a pinned immutable model version. |
| Temperature/top-p/seed and thinking | Partial | `RequestPolicy` explicit settings/default omissions; memory/answer thinking settings | Omissions are recorded honestly. Temperature/top-p are not exposed experiment controls; explicit seed is rejected. Recording a default is not controlling it. |
| Exact prompts, examples, source and output | Yes | Request/source/candidate/replacement/context artifacts and hashes | Raw messages would preserve examples, but there is no dedicated ICL treatment or prompt-optimizer lineage field. |
| Query-aware versus future-query-unknown compression | Partial | Current ingestion-before-QA protocol; archived compressor inputs | Current compaction is future-query-unknown. Explicit policy metadata would help if other compressors are added. |
| Separate formation/compaction/answer/judge usage | Yes, conditional on returned usage | Provider ledger, operation IDs, `overall.construction`, coverage/lower bounds | Unknown stays unknown. Retry/regeneration work is retained. |
| Monetary cost with price provenance | Missing | `api_cost_usd` remains unknown | Need an explicitly dated price table/currency/tier and cache treatment before calculating dollars. |
| Compaction/answer latency | Yes; summaries partial | Event/attempt seconds, request `provider_seconds`, phase timings | Recording/checkpoint overhead is included in application wall time. No standard campaign compaction p50/p95 report yet; raw times allow one. |
| GPU memory, KV cache bytes, inference FLOPs/EPR | N/A for remote provider; unmeasured locally | Hardware identity records OS/CPU/Python, serialized byte measures | File bytes/provider tokens cannot substitute for these quantities. |
| Downstream QA score | Yes | Per-case correctness, exact match, token F1, rubric, failure-aware summaries | Useful task outcomes, but not direct memory fidelity. |
| Proposition survival, qualifiers and contradictions | Missing | Source/output artifacts exist; source IDs are `lineage_only` | No `preserved`/`lost`/`contradicted` proposition annotations or semantic preservation evaluator. |
| Judge calibration for compression fidelity | Missing for this task | Existing answer-review/calibration facilities are separate | A QA judge does not automatically validate a proposition-preservation judge. |
| Repeats and statistical uncertainty | Partial | Sweep `repeat`, `compaction_campaign`, stable question/source identity | No paired campaign aggregator, clustered bootstrap, confidence intervals or variance decomposition. Failure bounds are not confidence intervals. |
| Learned-policy/prompt optimization split | Missing/N/A currently | Frozen current prompt and its hash are recorded | Add optimizer/development/evaluation split and selection trace only when such optimization exists. |

Source checked: [Compaction.py](../src/Compaction.py),
[Benchmark.py](../src/Benchmark.py), [RequestPolicy.py](../src/RequestPolicy.py),
[ResultAnalysis.py](../src/ResultAnalysis.py),
[ExperimentRecording.py](../src/ExperimentRecording.py),
[AuditProvenance.py](../src/AuditProvenance.py), and
[compaction_sweep.py](../tools/compaction_sweep.py).

## Metric mismatches that matter

### Compression factor versus retained percentage

KEEP-Bench Table 3 uses aggregate source length divided by aggregate output
length. Our current summary is the arithmetic mean of per-event retained
percentages. For input counts B and output counts A:

```text
Current mean retained percentage = mean(100 * A_i / B_i)
Aggregate compression factor     = sum(B_i) / sum(A_i)
Aggregate retained percentage    = 100 * sum(A_i) / sum(B_i)
```

These formulas are not interchangeable. For inputs 100 and 900, with outputs
50 and 90, the mean retained percentage is 30%; the aggregate retained percentage
is 14%, giving a 7.14x aggregate factor. Inverting 30% gives the wrong factor.
This example is arithmetic, not an experimental result.

For one-time comparisons, use one committed final operation per independently
formed conversation, with a matched cohort. Keep no-op references and failures
explicit. Do not combine intermediate repeated states into a “full-conversation
retention” claim: repeated source states overlap and already contain lossy summaries.
Tokenizers also differ across papers; re-count under an explicitly named tokenizer
before attempting a numerical cross-paper comparison.

### Task success versus memory fidelity

We have exact source/output text needed for later preservation evaluation. That
does not mean we already measure it. A QA prediction can be correct despite lost
supporting details. Conversely, retained evidence can coexist with reader failure.
An external fidelity evaluator should compare frozen outputs against separately
prepared propositions, recording labels and uncertainty without returning those
propositions to the compressor.

KEEP-Bench's compressor sees the question, whereas ours does not. Transfer the
diagnostic idea, not its QA access or raw scores. Its evidence-conditioned sentence
budget should not silently determine our future-query-unknown compressor budget.

### Repeated measurements versus independent samples

Multiple LoCoMo questions share one conversation/memory construction. A proposal
for our analysis is a paired bootstrap over matched conversations, retaining their
questions together, with repeats handled as nested construction/reader variability.
Do not directly reuse another benchmark's instance resampling unit. Also distinguish
new independent memory formation from frozen-state resume; resume is not a fresh
stochastic replicate.

## Proposed priorities, not implemented in this follow-up

1. **Derive comparable summaries from existing records:** declared aggregate factor,
   weighted retained percentage, per-depth/per-conversation curves, compression
   latency percentiles, paired source/question cohort checks, and explicit failure
   coverage. Give each derived metric a definition/version and cohort.
2. **Add a separate fidelity evaluation artifact:** proposition-set reference/hash,
   target snapshot/output reference, `preserved`/`lost`/`contradicted`/`uncertain`
   decisions, judge settings/request identities and human-validation sample. Keep
   QA outcome and lineage fields unchanged; neither owns semantic survival labels.
3. **Add campaign statistics:** match runs by dataset/question/source/prompt/policy
   identity; report repeats and conversation-clustered paired intervals, rather
   than treating every QA item as independent.
4. **Expose new scientific treatments only if studying them:** protected raw tail,
   separate turn cadence, compressor/reader model choices, decoding/thinking
   controls, and prompt-optimization provenance. These change the method and should
   not be introduced as mere recording fields.
5. **Optional economics/local-compute extension:** dated pricing metadata for dollars;
   actual hardware/runtime measurement for local compressors. Leave remote FLOPs,
   KV bytes and unsupported seed controls unavailable.

The first three improve comparison most directly without copying a different
benchmark's task or introducing future-QA leakage. No optimum percentage, new
quality result or statistical significance is inferred from this audit.

## Existing result check and validation

Read only bounded metadata from `data/result/locomo-results(delta_k=20).json`:
schema 2, module `delta`, 100 cases, **no recording archive**, no compaction campaign
metadata. Schema 2 alone does not imply the new archive exists. This is an older
architecture run; it cannot be assumed to contain current compaction fields.

Validation for this follow-up: source inspection, primary-paper method/appendix
reads, the bounded JSON metadata check and Markdown whitespace check. Application
tests were not rerun because this follow-up changes research documentation only.
The earlier implementation's 301-test result is separate evidence, not a fresh
test result for this research task.
