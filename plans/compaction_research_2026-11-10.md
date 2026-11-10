# Compaction: research and proposed implementation

Date: 2026-11-10, Asia/Hong_Kong. Originally prepared as a research/design proposal without application changes. The user subsequently approved implementation. The local implementation and offline validation are complete; see the [implemented specification](../spec/memory/compaction.md) and progress/updates logs. The research rationale and proposed future experiments below are retained as the decision record. No provider-backed study has been run.

## Recommendation and user preferences

Add a standalone `compaction` memory architecture. Replace the active conversation memory with a shorter, inspectable continuation summary, then accumulate new turns normally. Make retained percentage a variable. Support both one-time compaction of a frozen window and repeated compaction during ingestion; study them in that order, as requested by the user.

Proposed percentage definition: `retain_percent=30` means the complete rendered replacement memory occupies at most 30% of the current rendered memory's benchmark tokens. It does not mean remove 30%, or occupy 30% of the model's maximum capacity. The user answered “make it a variable”; this interpretation remains a proposal for approval. A separate trigger controls when compaction happens. No optimal percentage is established by the literature or this inspection.

Start with a provider-independent text summarizer using KAI3's existing API boundary. OpenAI native compaction is a different representation/backend and should be evaluated separately if later wanted. Implement fixed-percentage measurement first; add a learned/adaptive controller only after held-out evidence supports it.

## Repository findings

- `src/WindowHybridMemory.py`: Windowed Summary updates from every k incoming entries, combines those entries with the prior summary, retains the latest k raw entries, and flushes its partial batch before benchmark QA. Consequently k changes retention and update cadence together; summary and raw window can overlap.
- `src/Summarization.py`: rolling summaries have a fixed absolute cap; oversized output is locally truncated. This is not an explicit percentage-based replacement operation.
- `src/MemoryContext.py`: benchmark counts use the pinned wordpiece tokenizer, not the provider tokenizer. The current hybrid packer can shorten a detached summary and omit raw entries under the shared allowance. A percentage experiment must identify any such second transformation.
- `src/API.py` and `src/RequestPolicy.py`: memory formation currently calls DeepSeek through the shared request/accounting boundary. Native OpenAI encrypted compaction cannot be inserted as ordinary text here.
- `src/Diagnostics.py`, `src/Benchmark.py`, `src/ResultAnalysis.py`: existing formation/answer/judge accounting and unknown-usage handling should be extended, preserving missing usage as unknown.
- `src/Benchmark.py`: currently one architecture per run; ingestion precedes QA; questions/predictions are not written back. Resume may rebuild memory. Reusing a frozen compaction artifact requires an explicit new contract, rather than assuming current resume reproduces a stochastic summary.
- No applicable AGENTS.md was found in the repository search or checked parent paths. Working tree was clean during inspection.

The [4 November decision brief](decision_brief_2026-11-04.md) records 36/100, 34/100, and 35/100 for windows 10, 20, and 50 respectively. The window-50 export's filename says 100; configuration is authoritative. Known memory-plus-answer token lower bounds decrease from 3.65M to 2.51M to 1.19M, but all three runs have missing usage. This supports the hypothesis of lower formation cost with less frequent updates; it does not establish accuracy equivalence or isolate batching from retention. The user now authorizes planning the new module despite earlier plans deferring architecture expansion.

## Research method and stopping rule

Searched official product documentation, primary papers, author repositories, and the October 2026 survey; followed references into adaptive policies, repeated-loss measurements, controlled budget studies, and November 2026 releases. Opened primary sources rather than relying on search snippets for the central recommendations. Checked revised versions of ACON and Complexity Trap after discovering that initial versions differ from current abstracts. Some adjacent work below was screened at abstract level and is marked accordingly.

Search families covered native compaction; summarization versus masking; token/extractive compression; learned/context-editing policies; repeated summary drift; constraint preservation; rate-distortion objectives; LoCoMo comparisons; latency/cache economics; and target-ratio controls. Final targeted searches primarily returned already covered methods, adjacent implementations, or secondary commentary without changing the proposed first experiment. This is practical design saturation as of the review date, not proof that no further research exists. Search-result recency labels were not treated as publication dates. CompactionBench's preprint was posted 9 November 2026, verified on its landing page.

### Evidence and implications

| Primary source and review depth | Finding relevant to KAI3 | Limit and design implication |
| --- | --- | --- |
| [OpenAI compaction guide](https://developers.openai.com/api/docs/guides/compaction), official guide and endpoint reference | Server-side threshold compaction and explicit `/responses/compact` produce compacted state; standalone output may retain other items alongside an opaque encrypted item. | The returned standalone window is canonical and should be passed onward intact. No user-selected retained-percentage field was found in the reviewed endpoint. Use a text compressor for a measurable cross-provider ratio sweep; do not describe it as native Codex compaction. |
| [Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), engineering article; [on-demand API](https://platform.claude.com/docs/en/build-with-claude/compaction-on-demand), official API documentation | Continuation-oriented summarization preserves progress and important state; the API supports explicit history replacement. | Aggressive compression can lose details. Calls must fit the model window; output limits can include thinking. Preserve current goals, decisions, unresolved work, entities, and chronology. |
| [DeepSeek harness compaction](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/README.md), first-party README | Trigger pressure, retained budget, output reserve, and recent-tail retention are distinct; compaction is transactional around balanced history spans. | Engineering evidence, not a comparative research result. Borrow separate controls and atomic replacement, without assuming KAI3's API has the same capabilities. The main-branch document is mutable. |
| [Complexity Trap, v3](https://arxiv.org/html/2508.21433v3), full paper | On the tested SWE-agent configurations, observation masking competes strongly with LLM summarization; formation calls and longer trajectories affect total cost. The revised version adds a hybrid strategy. | Coding observations dominate those traces; LoCoMo does not have equivalent tool outputs. Include a budget-matched recent-turn baseline, but do not rename dropping dialogue “observation masking.” |
| [ACON, v3](https://arxiv.org/html/2510.00615v3), full method, ablations, limitations | Failure-driven natural-language compression guidelines improve preservation without changing the agent; threshold ablations show cost/quality trade-offs. | Reported peak-token reductions of 26–54% are benchmark/model-specific. Thresholds are not retained percentages. Optimize prompts only on development data, then freeze them. |
| [LLMLingua-2](https://aclanthology.org/2024.findings-acl.57/), primary paper abstract | Task-agnostic extractive token selection offers a different way to control prompt size. | A useful later compressor baseline; token pruning is distinct from a coherent continuation summary. It adds model/dependency and deployment choices outside the first implementation. |
| [AgentFold](https://arxiv.org/html/2510.24699v1), full method sections | Multiscale summary blocks plus a verbatim latest interaction support proactive context management. | The trained web-agent result does not isolate a percentage-only intervention. Start with a fixed strategy; make recent-tail retention a separate later ablation. |
| [LongSeeker](https://arxiv.org/abs/2605.05191), abstract screening; [AdaCoM](https://arxiv.org/abs/2605.30785), abstract screening | Context editing can adapt to relevance and agent capability; external controllers can manage a frozen agent. | These involve training and multiple actions, not a proven universal compression ratio. They motivate future controllers, not an initial RL implementation. |
| [Focus](https://arxiv.org/abs/2601.07190), abstract screening | Agent-selected compression reported token savings with unchanged success on five coding instances. | N=5 and 3/5 success in each arm are weak evidence of general accuracy preservation. Useful proof of possibility only. |
| [ACM](https://arxiv.org/abs/2607.23809), abstract screening | Offloading discarded content and retrieving it later makes compression recoverable. | Recoverable archive access changes the information available to the agent. Keep archive-assisted variants separate from pure compaction and count their storage/retrieval cost. |
| [Rate-distortion view](https://arxiv.org/abs/2607.08032), abstract screening | Memory compression should retain downstream utility under a budget; unknown future queries and repeated loss are central difficulties. | Conceptual framing and benchmark proposal do not establish an optimal ratio. Use a constrained quality/cost objective and measure repeated operations. |
| [Compaction Cliff](https://arxiv.org/html/2608.22752v1), methods, budget boundary, limitations | Type-specific retention preserves constraints better than treating every line alike; repeated rounds amplify loss. | Exact protected material has a minimum feasible budget. Some downstream comparisons are not equal-token comparisons. Count protected content inside the budget and report infeasibility rather than silently relaxing the percentage. |
| [Lost in Context Compaction, v2](https://arxiv.org/html/2608.11242v2), full evaluation structure | Semantic constraint retention and downstream compliance differ; separate extraction can preserve constraints better. | These are study-specific outcomes. For KAI3, distinguish preservation of a fact/constraint from the reader's use of it; do not assume a structured prompt guarantees fidelity. |
| [Continuous Context Management](https://arxiv.org/html/2609.35540v1), methods/results | Every-turn memory replacement greatly reduces prompt growth but reduces task success for most tested unfine-tuned models. | Lower token count alone is not success. Frequency and recursive depth must be measured independently of retained percentage. |
| [Benchmarks Are Surprisingly Compaction-Friendly](https://arxiv.org/html/2610.31778v1), methods and limitations | Stable task scores can coexist with lost constraints, especially when task state is recoverable from disk. Effects vary by model and threshold. | Few tasks and one scaffold limit generalization. Add delayed-detail and correction probes; LoCoMo QA is not a coding-agent effectiveness test. |
| [Paired conversational compaction study](https://arxiv.org/html/2611.09807v1), full method and limitations, submitted 6 November | Reports a four-category advantage for fact memory over transcript RAG, but a much smaller nonsignificant all-category advantage; wording-sensitive questions favor source text. | This is facts plus retrieval, fusion, raw-turn hydration, and an answer-type gate, not whole-window percentage compaction. Its adversarial references differ from KAI3's abstention protocol. Do not transfer scores, category meaning, or its sample-size rule. |
| [WAAC](https://arxiv.org/html/2611.08865v1), method screening, submitted 6 November | Workflow dependencies can determine what older evidence must survive compression. | This adds learned workflow experience and dependency analysis; useful motivation for structured preservation, not a simple ratio baseline. |
| [SpecCompact](https://arxiv.org/html/2611.06876v1), method/results/limitations, submitted 4 November | Structured-slot drafting and verification target summarizer latency while preserving information. | A trained drafter and multiple verification calls add complexity. Record compressor latency now; defer speculative generation until overhead is demonstrated locally. |
| [CompactionBench/APEC](https://www.microsoft.com/en-us/research/publication/benchmarking-long-horizon-agent-context-compaction-with-compactionbench/), author abstract; [dated preprint](https://www.preprints.org/manuscript/202611.0780), posted 9 November | Production analysis and repeated-session evaluation highlight foreground compaction delay and cache disruption; progressive background preparation aims to reduce both. | Very recent preprint, not independently reproduced here. Record cache usage and end-to-end latency; defer asynchronous replacement and its concurrency complexity. |
| [Interaction costs beyond task completion](https://arxiv.org/abs/2608.16370), abstract screening | Reacquisition can rise while completion stays similar; effects depend on environment. | KAI3's direct QA has no reacquisition tools. Do not invent that metric for QA; count extra tool/read calls only in a future tool-using evaluation. |
| [October 2026 survey](https://aclanthology.org/2026.emnlp-main.2396.pdf), taxonomy and evaluation sections | Separates targets, mechanisms, and controllers; distinguishes decision errors, information loss, and later access failures. | A synthesis, not independent effectiveness evidence. It supports logging state quality, recovery, propagation, and overhead alongside accuracy. |

## Proposed module contract

### Percentage and controls

For current active memory W, use one versioned renderer R and pinned tokenizer T:

`N_before = T(R(W))`

`target_tokens = floor(N_before * retain_percent / 100)`

`actual_retain_percent = 100 * T(R(W_after)) / N_before`

Labels, separators, and any explicitly retained raw tail count in both sides. Fixed system instructions and the new user query do not. Benchmark tokens measure experimental size; provider usage measures billed work. Store both identities and never equate them.

Proposed controls:

| Field | Meaning |
| --- | --- |
| `retain_percent` | Finite numeric value in (0, 100]; booleans/NaN/infinity rejected. 100 is an exact no-op reference with no compression call. |
| `compaction_mode` | `one_shot` or `repeated`; manual compact remains available in live chat. |
| `compaction_trigger_tokens` | Active-memory trigger H for repeated mode; independent of retained percentage and any turn-count k. |
| `compaction_scope` | Initial implementation: the entire active memory, including the existing compacted state. No hidden archive retrieval. |
| `memory_context_tokens` | Reader allowance B; separate from H. A matched percentage experiment must fit the resulting state without another lossy packing step. |
| `compaction_max_attempts` | Proposed fixed initial policy: first generation plus at most one shorter regeneration after budget/format validation failure; transport retries remain governed by RequestPolicy. All attempts counted. |

Use 50% as a documented initial UI example, not a research-backed default optimum. Accept arbitrary valid percentages, not only sweep values. Keep recent-tail preservation at zero for the first whole-window study; a later version may expose it as a separate factor.

### One-time operation

1. Freeze the current active state, its renderer/tokenizer identity, source IDs, and state hash. An experimental source window must be selected chronologically without looking at QA labels or evidence.
2. Generate each percentage independently from that same uncompressed snapshot. Never obtain 25% by compressing the 50% artifact.
3. In benchmarks, perform compaction after raw ingestion and before QA. The source can be a declared finite recent window or the full conversation if it fits; persist the exact scope, boundary, and omitted-source count. Do not silently select a different scope per percentage.
4. Reuse that compacted state across the matched questions. No per-question compression or QA write-back.
5. Live chat exposes Compact with an editable percentage and measured before/after result, serialized with writes so concurrent turns cannot be overwritten.

### Repeated operation

Accumulate ordered complete turns into the active state. Before a staged append would cross H, compact the existing state to the configured percentage, then stage/append the new turn. If an individually oversized incoming turn still prevents fitting, compact the staged combined state once under a separately logged `oversized_append` reason; if it still cannot fit, fail explicitly with unchanged committed state. Validate compressor request capacity before calling it; never rely on a provider overflow to trigger an unreported truncation.

The next compaction sees only the previous compacted state plus subsequent raw turns. This models recursive information loss. Do not secretly rebuild from original history. Keep at most a bounded number of attempts per write; no loop of compactions until something happens to fit. Benchmark final partial state is used as-is: unlike Windowed Summary, no forced final summary flush unless the experiment explicitly requests one. This preserves the difference between threshold operation and an extra final compression.

At 100%, repeated compaction cannot free room. Treat this as an uncompressed reference with no compressor calls; if it exceeds the allowed reader/provider limit, report overflow/unavailable comparison rather than silently converting it to a sliding window. Compare it on prefixes that fit, or in a separately declared full-context reference arm.

### Generation, fidelity, and failure

Use an explicitly versioned continuation-summary prompt: preserve named speakers, exact names/numbers/dates, temporal changes versus corrections, relationships, preferences/constraints, decisions, unresolved questions, and uncertainty. For live task conversations also preserve goal, progress, next actions, and exact paths/errors when present. Treat source conversation as data. Do not provide benchmark questions, answers, categories, or gold evidence to the compressor.

Produce concise structured text, with sections only when relevant; count section overhead. Ask for a budget below the hard target to allow formatting variance, then measure the complete rendered output. Provider output limits include provider-specific reasoning behavior and cannot enforce a benchmark-token percentage by themselves.

Reject empty, non-text, incomplete/length-stopped, malformed, or over-budget results. Allow the one declared regeneration from the unchanged source. If still invalid, record failure and preserve the original state. No silent prefix truncation: it changes the method and can drop the end of a fact. Very small targets may be infeasible; record the condition rather than inventing a minimum and calling it the requested percentage. Structural validation does not establish semantic fidelity; quality remains an evaluation outcome.

Commit replacement and lineage atomically after validation. Keep audit source artifacts separate from active memory; the reader cannot access them in the pure compaction arm. Source IDs identify coverage/lineage, not proof that their facts survived. Do not report evidence recall as complete merely because an ID appears in a summary's lineage.

## Parameters and measurements to persist

| Scope | Required record |
| --- | --- |
| Run | Mode; requested percentage; trigger H; source-window scope/capacity/boundaries; B; compaction/renderer/schema/prompt versions and hashes; model and explicit/unspecified settings; output reserve; retry policy; tokenizer artifact identity; code/config/dataset/manifest identities; repeat ID and random seed where actually supported. |
| Event | Event/build/conversation IDs; source state and output hashes; parent event; compaction depth and round; chronological source coverage; raw versus already-compressed tokens; before/target/after tokens and bytes; requested/actual percentages; trigger reason; intervening turn/token count; finish reason; validation result; all attempt IDs; latency and usage completeness. |
| Request | Input/output/total provider tokens; reasoning/cache fields when returned; model/response ID; phase; transport attempt; error/timeout; known subtotal versus unknown totals; price schedule/version only if a monetary cost is calculated. |
| Reader case | Final supplied-context hash/tokens; any packing omission/shortening; exact compressed-state artifact identity; QA manifest key; answer/judge usage and latency; completion/failure status; correctness and abstention outcome. |
| Aggregate | Total compaction calls/attempts/failures; peak and final active size; cumulative formation-plus-answer usage; judge usage separately; cache coverage; wall time/compaction time; logical active-memory storage and separate audit/snapshot storage. |

Retain the existing unknown-usage contract. Missing usage is not zero. Do not sum campaign rebuilds as if each were a new unique memory, or hide retry/rebuild cost. For one compacted memory answering Q questions, expose formation cost plus sum of Q answer costs; amortized formation/Q is an additional labeled measure, not a replacement for the total.

## Experiment plan

### A. One-time percentage curve

Suggested exploratory grid: 100, 75, 50, 35, 25, 15, 10, and 5 percent. These are starting points, not fixed API choices. Freeze identical source snapshots and QA selection, compressor prompt/model/settings, reader/judge settings, and tokenizer. Independently build each percentage from its raw source. Repeat stochastic builds and reader calls as permitted by a later frozen cost budget; preserve every artifact.

A percentage-isolation comparison needs B large enough to admit the entire uncompressed reference and every replacement. KAI3's usual B=2,000 cannot automatically support this for a large source window. Either use windows that fit B or use a declared larger common allowance subject to the conservative provider request guard. Otherwise run a separate B=2,000 deployment study and explicitly report secondary packing effects. Never label differently clipped contexts a pure percentage experiment.

Compare with the raw source (100%), budget-matched recent whole turns, existing Rolling Summary, and Windowed Summary. Hold their declared settings fixed; architecture comparisons remain separate from the within-compaction ratio effect. A full-conversation baseline is a reference, not a guaranteed quality ceiling.

Report all five KAI3 categories with validated reference/abstention semantics, per-conversation results, exact/F1 diagnostics and calibrated binary judging. Include delayed facts, exact wording, numbers, speaker attribution, temporal updates/corrections, multi-hop links, and abstention. Inspect summaries on blinded preservation probes outside compressor inputs. Complete actual human judge calibration before effectiveness claims; implementation need not wait for that study.

Use paired outcomes with uncertainty clustered by conversation; only ten LoCoMo conversations limit precision. Repeated model calls do not create independent conversations. Predefine sample size, practical quality tolerance, and multiple-comparison treatment before confirmation. Do not infer equivalence because a significance test fails. Tune on development conversations and confirm the chosen percentage on untouched conversations or an external held-out set.

### B. Repeated-compaction study

Fix H first and vary percentage; then cross a small percentage shortlist with several H values. Different percentages naturally change compaction frequency: the end-to-end effect includes that change. To isolate recursive loss, run a separate fixed-source checkpoint/depth study. Record depth, age of queried evidence, total calls, peak memory, and quality after multiple rounds. Use conversation-prefix questions only where their required evidence already exists; final-conversation QA alone misses intermediate deterioration.

An optional diagnostic rebuild from all raw history at the same output budget can help separate accumulated drift from insufficient final capacity. Label it an offline intervention with extra source access, never as the repeated deployment policy.

### C. Optimal and adaptive choice

There is no single optimum without an objective. First plot accuracy versus total provider work, reader-context size, and latency; identify nondominated configurations. A proposed selection rule is minimum total formation-plus-answer cost subject to held-out accuracy loss no greater than a predeclared epsilon and acceptable completion/fidelity. Epsilon and cost/latency priorities need agreement before running confirmation, not before implementing measurement.

An adaptive controller could choose percentage from a discrete shortlist using only currently observable features: token pressure, recent growth, existing compaction depth, explicit dates/numbers/corrections, and protected-state load. Train/tune only on development data; freeze before testing. Log features, chosen action, and controller overhead. Compare against the best fixed percentage and a simple pressure rule. Do not use future QA labels, gold evidence, or evaluation category to select the action. LLM self-rated confidence is not a fidelity guarantee. Archive recovery, protected anchors, new compressors, or training introduce separate experimental factors.

## Implementation sequence for approval

1. Add `src/Compaction.py` with injectable tokenizer/compressor, write/compact/inspect/context-candidate contract, atomic state replacement, validation, event lineage, and versioned export/import of frozen active state. Keep events and source artifacts from being rendered as reader memory.
2. Register the architecture and applicable controls in `MemoryConfig.py`, `MemoryFactory.py`, and `Benchmark.py`. Add first-class one-shot preparation and repeated ingestion; keep exactly one architecture/configuration per run. Add a small sweep orchestrator that creates independently configured runs from shared frozen source manifests rather than changing that contract.
3. Extend `Diagnostics.py`, `AuditProvenance.py`, and result analysis for per-event accounting, requested/actual ratios, complete usage scope, and state identity. Extend compaction resume/artifact reuse checks explicitly; changing policy/model/tokenizer/prompt/source identity must prevent silent reuse. Count any actual rebuild as a new ingestion attempt.
4. Integrate chat configuration/manual Compact in `app.py`, `index.html`, and `workspace.js`, plus CLI options in the existing benchmark/terminal surfaces. Serialize compaction with chat writes and preserve cancellation. Show the percentage, mode/trigger, actual result, and clear failure feedback.
5. Extend Compare Runs (`ResultAnalysis.py`, `compare.js`, and related templates/styles as needed) with compaction configuration labels, requested/actual percentage and compaction-overhead metrics available in the existing scatter controls. Preserve legacy imports and missing-value behavior. Display reader-context size separately from total provider usage.
6. Add focused offline tests: percentage math/rounding and framing; 100% no-op; invalid/tiny/empty inputs; Unicode; incomplete and over-budget output; bounded retry accounting; rollback on errors/cancellation; repeated lineage; one-shot source identity/no QA leakage; oversized-turn handling; no hidden archive access; concurrent chat writes; frozen artifact restore/reuse; resume incompatibilities; unknown usage; frontend payloads and legacy comparisons.
7. Run relevant regressions and the required offline suite, then desktop/mobile UI verification with synthetic data. Write `spec/memory/compaction.md` and update plan register, README, progress, and updates to distinguish implemented behavior from unrun studies.

The user approved this local implementation scope and offline validation, which are now delivered. Provider-backed sweeps, judge calls, model training, native OpenAI backend integration, and adaptive-policy deployment remain later execution decisions with concrete budget/configuration. This document proposes their methodology, not that they have been run or approved.
