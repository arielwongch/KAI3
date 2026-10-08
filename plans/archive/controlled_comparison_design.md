<!-- Historical document; see the notice below before interpreting its status. -->
> Historical record, archived on 2026-10-08 from `spec/locomo_controlled_comparison.md`.
> First recorded in Git: 2026-10-06, commit `c84cb77`. This is a commit date,
> not a verified proposal/approval or deployment date. The body preserves the
> pre-reorganization working-tree text, including later edits and old status claims.
> "Current", "planning only", dates, and open questions below describe that
> historical document and are not current project status.
> See the [plan index](../README.md) for reconciled status and the
> [specification index](../../spec/README.md) for implemented behavior.

# Controlled LoCoMo memory comparison

Status: implemented on 6 October 2026. This document defines protocol v3 and
schema-v2 exports; saved legacy results retain their original interpretation.
It specifies the five priority changes before another paid comparison. The current implementation is in
`src/Benchmark.py`, the memory modules, `src/index.html`, and `src/workspace.js`.

See [LoCoMo memory module specifications](../../spec/README.md) for each
condition's implemented write, storage, retrieval, and failure behavior.

## Objective and scope

Compare how recency, summary, original-turn retrieval, and fact memory preserve
useful conversation information under a common memory-context allowance. Keep
question-only and full-context conditions as separate reference baselines.
Equal context allowance controls one confound; it does not equalize ingestion
cost, stored information, or representation quality. Report these differences.
Full context is a reference condition, not a guaranteed performance upper bound.

Keep chronological ingestion, fresh memory per conversation, the same answer
model and prompt, no QA write-back, and reference answers/evidence available only
to scoring after prediction. Never use annotated evidence to select memory,
extract facts, tune a case's budget, or expand retrieved context.

This change applies to the benchmark. Preserve live-chat behavior and its
existing `retrieve(query, k)` contract. Hybrid memory, neighbouring-turn vector
expansion, and attributed summaries are later experiments. Summary batching is
implemented: new runs default to session-bounded batches of up to 20 turns and
12,000 characters, retaining a single oversized turn intact. Set
`summary_batch_size=1` for per-turn updates. Record batching separately because
it changes summary construction and cost; resume preserves saved batch settings.

## 1. Separate baseline conditions

Expose these six choices in the benchmark UI and CLI:

| Condition ID | Display name | Supplied conversation context |
| --- | --- | --- |
| `question_only` | Question Only | Empty; the shared answer prompt still applies |
| `full_context` | Full Context | All formatted turns, in chronological order |
| `sliding_window` | Sliding Window | Recent stored turns within the memory budget |
| `summarization` | Rolling Summary | Rolling summary within the memory budget |
| `vector_store` | Vector Retrieval | Similarity-ranked original turns within the memory budget |
| `fact_store` | Temporal Facts | Similarity-ranked current and historical facts within the memory budget |

Use explicit IDs for new runs. Both reference conditions use `NoMemory`
internally; full context bypasses retrieval. Keep `no_memory` in live chat.
Accept legacy benchmark `no_memory` plus `no_memory_context` as an input alias
and normalize it once. Reject conflicting old and new options.

Question-only receives zero memory tokens. Full context is exempt from the
memory budget and retains the separate request-context guard: reject an
over-limit request without truncating or silently converting it to retrieval.
Label both exceptions in setup, exports, and reports.

For old reports, derive the display label from explicit saved condition/input
mode or an unambiguous saved protocol. An old `no_memory` label alone does not
prove full context; show "No Memory (legacy; input mode unknown)" when ambiguous.
Keep the original JSON and historical scores unchanged.

## 2. A common memory-context token budget

Example sliding-window configuration:

```json
{
  "memory_context_tokens": 2000,
  "retrieval_k": null,
  "max_stored_entries": 10
}
```

Example summarization configuration:

```json
{
  "memory_context_tokens": 2000,
  "max_summary_tokens": 2000
}
```

The 2,000-token default is a proposed experiment setting, not a tuned result.
Budget sweeps are separate runs. Record all settings in exports. Validate positive
integers, rejecting booleans; allow `max_summary_tokens` no larger than the memory
context allowance for the primary experiment.

### Configurable retrieval and storage

Expose retrieval count and storage capacity as independent controls only for
sliding-window, vector, and fact memory. Summarization returns its one rolling
summary directly and needs neither control. `k` is the
maximum number of candidate records considered per question; storage capacity
is the maximum number retained across writes. Neither replaces the context-token
budget. A record means a dialogue turn for window/vector and a fact version for
facts; summary memory always holds one rolling summary.

| Setting | Meaning | Values |
| --- | --- | --- |
| `retrieval_k` | Consider the first k candidates in the module's ordering | Positive integer, or null for all candidates |
| `max_stored_entries` | Retain at most this many records | Positive integer, or null for unlimited where supported |
| `max_summary_tokens` | Maximum rolling-summary size | Positive integer; summary only |
| `memory_context_tokens` | Maximum rendered context supplied per question | Positive integer; all four memory conditions |

Expose settings according to module capabilities:

| Module | Retrieval k | Stored-record capacity | Summary-size limit | Context-token budget |
| --- | --- | --- | --- | --- |
| Sliding Window | Yes | Yes, finite | No | Yes |
| Vector Retrieval | Yes | Yes, finite or unlimited | No | Yes |
| Temporal Facts | Yes | Yes, finite or unlimited | No | Yes |
| Rolling Summary | No | No | Yes | Yes |
| Question Only / Full Context | No | No | No | Exempt |

Reject zero, negatives, booleans, and fractional counts. Use null explicitly;
the UI shows "All available" for retrieval and "Unlimited" for supported stores.
CLI uses `--retrieval-k all` and `--max-stored-entries unlimited` for these values.
The JSON example above is the sliding-window default; use unlimited storage for
vector/facts by default. Sliding window requires a finite capacity (default 10).
Summary exposes only its summary-size limit and context-token budget. Omit
`retrieval_k` and `max_stored_entries` from its normalized configuration, even
though it internally stores one summary. Reject explicitly supplied inapplicable
keys, including null/1 retrieval counts. Likewise, `max_summary_tokens` applies
only to summary and `fact_history_mode` only to facts. Reference baselines expose
no memory controls and reject explicit inapplicable settings.

Changing the selected module hides irrelevant fields and removes their values
from the submitted payload; keep drafts separately per module if needed. Use
module capability metadata to drive UI, API validation, CLI validation, and
exports so unsupported settings cannot silently affect a run. Shared CLI options
must default to an unspecified sentinel, allowing validation to distinguish an
omitted option from an explicitly supplied null/all value.

Finite window/vector capacity evicts the oldest ingested record first. Finite
fact capacity evicts the oldest observed version first, including historical
versions, after the whole extraction transaction commits; ties use stable IDs.
Confirming a fact does not refresh its creation order. Eviction removes its
searchable text/embedding; retained provenance remains auditable, and version
links to evicted records are marked unavailable. A finite fact capacity therefore
limits historical coverage and must be labelled in comparisons. Unlimited fact
storage remains the primary history-preserving baseline.

Limit candidates to k before token packing. Oversized candidates can be skipped
within that set, but do not pull replacements from ranks beyond k. The final
supplied count can be less than k because storage is smaller or the token budget
is exhausted. For example, capacity=20, k=8, B=2,000 means store at most 20
records, consider at most eight, and supply only whole records that fit B.
With capacity=10 and k=null, all ten window turns are eligible; with k=5 only
the latest five are eligible even if there is spare token allowance.

Keep these controls available through the module factory and a reusable context
builder, with the existing live-chat defaults unchanged. Benchmark UI/API/CLI
pass explicit normalized configuration rather than hardcoding counts. A future
chat settings UI can reuse them without changing the benchmark protocol.

For the primary controlled comparison use k=null for the three record-based
modules and a common B for all four memory architectures, allowing each to fill
its allowance. Summary supplies its single summary without a k setting.
Finite-k and finite-storage sweeps are
separate labelled experiments. Equal k does not imply equal information across
architectures. Export configured/effective limits, stored counts, evicted counts,
and candidate/supplied counts; resume must reject changed limits.

### Counting contract

Use one shared `BenchmarkTokenizer` for every memory architecture. For the first
implementation, use the tokenizer associated with the already-used MiniLM model
as a fixed benchmark counting convention, with full-text encoding, no special
tokens, and no model-length truncation. Pin its artifact revision and record the
tokenizer ID, revision, and artifact hash. The implemented revision is `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`;
exports include the loaded artifact hash.
Do not identify these counts as exact DeepSeek tokens: this tokenizer controls a
common experimental allowance, while provider-reported prompt tokens separately
measure actual API usage. A provider tokenizer can replace it in a separately
versioned protocol after validation.

Count the exact final memory-context string, including rendered speaker/date/
status labels, separators, and truncation markers. The budget excludes the
question and shared prompt instructions; report those separately. Retain the
existing conservative byte-based whole-request guard under its own explicit
name. Never fall back silently to bytes or whitespace counts if tokenization
fails; fail preparation before answer calls.

### Retrieval and packing contract

Add a benchmark-facing candidate method without changing live-chat retrieval:

```python
def iter_context_candidates(self, query: str, k: int | None = None) -> Iterator[MemoryEntry]: ...

def build_memory_context(module, query, token_budget, tokenizer,
                         retrieval_k=None) -> ContextResult: ...
```

Candidates are detached records with stable IDs and optional similarity scores.
The shared builder renders, packs, and counts them. `ContextResult` contains the
exact text, included entries/spans, token count, omitted/partial record counts,
and counting-method metadata. `direct_answer` consumes this result.

Candidate ordering:

- Window: all stored turns, newest first for selection; render selected turns
  chronologically. Apply configured k; with k=null include all ten when they fit.
- Summary: the single stored summary.
- Vector: all stored turns ranked by existing maximum chunk cosine similarity;
  preserve the existing deterministic tie-break rule. Apply configured k;
  there is no hardcoded top-five cap.
- Facts: all eligible versions ranked by cosine similarity, then observed
  revision and stable record ID. Current and historical records are eligible;
  apply configured k.

For window/vector/facts, include whole records greedily in candidate order,
skipping records that do not fit and continuing to smaller candidates. Do not
truncate factual or dialogue records in the primary experiment. If no whole
record fits, supply empty context and flag `all_candidates_over_budget`.
This makes fragmentation/long-record limitations visible rather than hiding
them in text cuts. Recount after final ordering and formatting; never exceed B.

Generate summaries with an explicit token-size instruction, then enforce the
stored summary cap locally. Preserve the longest token-aligned text prefix that fits with an
explicit truncation marker, using the same tokenizer. Count the final rendered
summary, record truncation, and do not perform a second unreported compression
call. A summary has no dialogue evidence IDs merely because earlier turns were
seen by the summarizer.

Diagnostics: `memory_context_tokens`, `memory_context_token_budget`,
`memory_context_bytes`, `candidate_count`, `included_count`, `omitted_count`,
`context_truncated`, exact supplied context, and tokenizer identity. Deprecate
the misleading byte-valued `retrieved_token_budget` for new reports; retain it
only when displaying legacy exports.

## 3. Fact provenance and evidence coverage

Versioned fact records contain stable `fact_id` and unique `version_id`, text,
speaker, source dialogue IDs, source sessions/dates, status, observed revision,
and links to prior/new versions. Preserve the source text and metadata snapshots.
Scope IDs to their conversation; never mix speakers during deduplication.

Extend extractor operations with explicit source IDs and supporting fact-version
IDs. The application resolves supporting versions into source dialogue IDs and
validates references against the input turn and supplied stored records.
The extractor cannot introduce arbitrary dialogue IDs. An exact repeated
assertion or explicit paraphrase confirmation uses a `confirm` operation to add
new support without creating another fact. An empty operations response adds no
provenance. A statement referring to an old fact does not automatically become
evidence supporting that fact.

Provenance must describe support for the emitted text, not every turn in the
update chain. For example, a newly asserted Microsoft employment fact gets the
Microsoft assertion's sources; it does not inherit Google's sources merely
because it supersedes the Google record. Historical records retain their own
assertion sources; transition/retraction sources are separate metadata.

For a case with nonempty annotated evidence E, calculate source coverage from
the union R of source IDs of fully supplied fact versions or original turns:

```text
evidence_recall = |unique(E) intersect R| / |unique(E)|
evidence_complete = unique(E) is a subset of R
```

Use `evidence_recall_basis = original_turn` for window/vector/full context and
`fact_source_provenance` for facts. Summary and question-only have no applicable
coverage measure. Empty evidence yields null, not zero. Show coverage denominators.
Fact source coverage is a provenance proxy: it does not establish that extraction
preserved every annotated detail. Keep the basis visible in comparative tables.

Optionally report accuracy conditional on complete/incomplete evidence coverage,
including group sizes, judged counts, and failure counts. Treat this as diagnostic
association, not proof of whether retrieval or reasoning caused a failure.

## 4. Preserve fact history without inventing temporal validity

Enable versioned history for benchmark fact memory only. Live chat retains its
existing current-state replacement/retraction behavior unless separately changed.

- Add: create a current assertion version with its provenance.
- Confirm: attach validated support to the existing assertion version.
- Supersede: mark the old version superseded and create a linked current version.
  Keep the old text, embedding, and assertion sources searchable.
- Correct: retain the old version as corrected and create a linked replacement.
  Render the old assertion as explicitly corrected, not a past true state.
- Retract: retain the old version with retracted status and transition evidence;
  render it as a withdrawn assertion, not a current truth.

The extractor distinguishes real-world change from correction of an erroneous
claim. Do not assume that every change of employer, preference, or location
negates a previous statement; use explicit conversational support. Reject
invalid IDs, duplicate targets, cross-speaker updates, malformed operations, and
unsupported source references atomically. Prepare all embeddings before commit.

Record `observed_from`/`observed_until` as conversation observations. Session
dates are not automatically real-world `valid_from`/`valid_until` dates. Store
event dates only when asserted, retaining the original wording and its sources.
Unknown real-world dates remain null. Render speaker, assertion text, observation
date/session, and status into QA context; these labels consume the budget.

Acceptance example: Bob's Google assertion survives a later Microsoft assertion
and is retrievable for "Where did Bob work before Microsoft?". A correction
"I never worked at Google" makes the old record explicitly corrected; it must
not be rendered as established past employment.

## 5. Failure-aware accuracy and complete denominators

Create the complete selected-question manifest before ingestion. Use its length
as `selected_count`, per category and overall, including questions blocked by
ingestion failure or not attempted before cancellation. Stable case keys remain
condition, sample ID, and question index. Persist each case's stage/status.

Every selected case belongs to one mutually exclusive state:

`judged_correct`, `judged_incorrect`, `judge_failed`, `answer_failed`,
`context_limit_exceeded`, `ingestion_blocked`, or `not_attempted`.

An invalid/length-limited answer is answer failure. A valid prediction with a
failed/invalid judge is judge failure; its deterministic metrics remain usable.
Retries retain attempt diagnostics but do not multiply case counts. Retry judge
failures by reusing saved predictions; never infer correctness from F1 alone.

Report these distinct metrics:

```text
judged_accuracy = correct_count / judged_count
completion_rate = judged_count / selected_count
end_to_end_success_rate = confirmed_correct_count / selected_count
```

Use null for zero denominators. The end-to-end measure counts every selected
question without confirmed correctness as unsuccessful, including pending judge
cases. This is operational success, not a claim that infrastructure-failed
predictions are semantically wrong. Label it provisional for active/interrupted
runs; never present a partial run as a completed architecture comparison.

Also report answer failures, judge failures, context-limit cases, ingestion-
blocked questions, not-attempted questions, and judged incorrect questions.
Counts must sum to `selected_count`. Show answer availability and judge coverage.
When there are unresolved cases, report confirmed accuracy bounds
`[correct_count / selected_count, (correct_count + unresolved_count) / selected_count]`
where unresolved excludes judged incorrect cases. These are accounting bounds,
not statistical confidence intervals.

Keep the current category-aware QA score, normalized EM, token F1, and judge
rubric fields. Their successful-case means must include their own denominators.
Add names explicitly; do not overwrite the meaning of historical `accuracy`.

## Reports, costs, and reproducibility

Setup exposes six conditions and the common context allowance. Show full-context
and question-only exemptions, retrieval/storage controls, and the counting
convention. Reports show judged
accuracy, end-to-end success, completion rate, failures, and evidence coverage
alongside QA metrics, context tokens, retrieval/answer latency, and storage.

Retain ingestion LLM calls, total API tokens, write latency, and session storage
growth. Add prompt/completion token breakdowns where the provider returns them;
missing usage is null, never zero. Do not fabricate monetary estimates. A future
cost estimator requires an explicit dated price source and separate answer,
judge, and ingestion totals. Storage continues to be labelled logical snapshot
size excluding embeddings/runtime; also count current and historical facts.

Use a new schema/protocol version. Export the selected-question manifest and its
hash, dataset hash, normalized condition, configuration, tokenizer pin/hash,
fact-history policy, prompt versions, model/settings, context packing policy,
exact context, predictions, failures, and per-stage usage. Hash prompt content
as well as storing version labels. Record dependency versions and deterministic
tie-break rules. Do not imply the provider model name pins provider weights.

Legacy reports remain readable with new fields shown as unavailable unless they
can be derived unambiguously. Do not fabricate total selected counts from saved
case counts. Keep imported data immutable. New resume validates protocol,
tokenizer, budget, fact policy, question manifest, and prompt/model compatibility;
also validate retrieval count, storage capacity, and eviction policy;
reject mixed-protocol resume. Legacy jobs can resume only under their original
supported protocol, otherwise offer a new run. Rebuilding generative memory can
change it; retain prior snapshots and mark reused predictions with their original
context/ingestion identity rather than attributing them to the rebuilt memory.

## Implementation sequence and acceptance checks

1. Add versioned config, explicit condition IDs, manifest, and baseline aliases.
   Verify both fresh reference prompts and legacy display/input normalization.
2. Add shared tokenizer/candidate packing and summary token caps. Verify exact
   rendered counts never exceed B, ten window turns are supplied when they fit,
   vector/fact selection can exceed five entries, empty/oversized candidates,
   separators, Unicode, stable ordering, and no silent tokenizer fallback.
   Verify k=1/5/all, capacity below k, finite-capacity eviction, whole-record
   packing within the first k candidates, unsupported settings, and limit
   validation/resume rejection. Ensure finite fact eviction is reported.
3. Add benchmark fact versions and validated provenance. Verify supersession,
   correction, retraction, confirmation, historical retrieval, speaker isolation,
   repeated-source deduplication, and atomic extraction/embedding failures.
4. Add manifest-based accounting and evidence coverage. Verify the example
   90 correct + 10 judge failures gives 100% judged accuracy, 90% completion, and
   90% end-to-end success; account for ingestion failure and cancellation too.
5. Update UI, CLI, exports/imports, resume checks, and README. Verify old reports
   retain their saved values and ambiguous baseline labels stay ambiguous.

Run mocked protocol and semantic-memory tests first, followed by report/import,
recovery, lifecycle, and relevant frontend tests. Confirm live-chat behavior
remains unchanged. No paid model calls are needed for acceptance tests.

The first comparison uses all selected conditions with identical conversations,
categories, ordered question manifest, answer/judge settings, and B=2,000 for
the four memory conditions, k=null for window/vector/facts, window capacity=10,
and unlimited vector/fact
storage. Preserve separate runs/exports. Do not compare the
existing 100-question full-context result directly with a differently selected
new run. A matched full-context run is needed for the final comparison.

Later ablations may evaluate vector neighbours, multiple budgets, summary batch
size, or current-only versus historical facts. Version and label each condition;
keep hybrid memory outside this first comparison.
