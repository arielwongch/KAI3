# Compaction comparison and evidence fidelity

This implements the first three priorities in the
[paper audit](../../plans/compaction_paper_recording_audit_2026-11-10.md).
It adds analysis and offline annotation/statistics workflows, without changing
the compressor, reader budgets, prompts, or access to future QA. The
[recording contract](experiment_recording.md) remains the owner of exact artifacts.

## Aggregate compression measurements

Enriched reports add `comparison.rows[].overall.compaction.analysis` (version 1).
Compare Runs exposes **Compression factor (one-shot)**, **Weighted retain
(one-shot %)** and **Compaction event latency p95** on either chart axis.

```text
aggregate_compression_factor = sum(before_tokens) / sum(after_tokens)
weighted_retained_percent   = 100 * sum(after_tokens) / sum(before_tokens)
mean_retained_percent       = mean(100 * after_tokens / before_tokens)
```

These are different aggregates. Inputs 100/900 and outputs 50/90 produce a 7.14x
factor, 14% weighted retention, and 30% mean retention. Tokens measure text size,
not preserved facts. Tokenizer identity stays attached to the analysis.

- `final_one_shot_cohort` uses exactly one committed completed/no-op operation per
  selected conversation in the latest construction. Every selected conversation
  must have complete formation and valid nonempty token counts. Otherwise its
  headline factor/weighted percentage is unavailable, not zero. A 100% no-op counts
  as a 1x reference. Missing/empty counts and excluded sample IDs are disclosed.
- `operations`, `by_conversation` and `by_depth` describe committed operations in
  latest snapshots. Repeated sources overlap and contain previous lossy summaries:
  their factor cannot be called full-original-conversation retention.
- `history` deduplicates event IDs across memory snapshots, ingestion ledgers and
  resume history. Conflicting identities are excluded/disclosed. Status/no-op,
  rollback, unknown commit and missing identity counts remain available.
- Event/attempt p50 and p95 use measured nonnegative times across all deduplicated
  builds, including failures and rollback. Measured/total counts disclose missing
  timing. Wall time includes recording/checkpoint overhead. A percentile of
  measured times is not a complete timing total if records are missing.

Existing mean-retention and overhead fields remain compatible. Old reports still
open; absent counters/formation evidence do not acquire a complete new cohort.

## Separate evidence-survival annotations

`tools/compaction_evaluate.py` never calls a model. It consumes a complete results
archive plus a user-authored proposition set. Assertions must be checked against
their source by the author; `source_verified: true` records that assertion, not an
automated proof. Example input (replace IDs/hash with the actual dataset's values):

```json
{
  "version": 1,
  "dataset_hash": "copy dataset_hash from the results export",
  "author": "reviewer-id",
  "samples": [{
    "sample_id": "sample-id",
    "propositions": [{
      "id": "p1",
      "text": "Alice drinks tea only on Sundays.",
      "source_ids": ["D1:1"],
      "source_verified": true,
      "kind": "qualifier"
    }]
  }]
}
```

Proposition IDs are unique within a sample; source IDs must exist in its archived
conversation. `kind` defaults to `fact` and can identify qualifiers, corrections,
relationships, or another declared subgroup. Do not encode unsupported gold
answers as supposedly verified source facts.

```powershell
python tools/compaction_evaluate.py prepare --report run.json --propositions propositions.json --output review.json
# Edit only review.items[*].label and rationale.
python tools/compaction_evaluate.py score --report run.json --review review.json --annotator reviewer-id --output fidelity.json
```

Preparation selects committed completed/no-op outputs from the latest recorded
construction for each proposition sample. For each operation, the immutable
`fidelity-manifest` stores source/output text, original artifact hashes, event/depth,
tokenizer and frozen memory identity. Each output, including intermediate repeated
operations, has a stable target ID. It evaluates the exact replacement text, not a
later transaction state containing additional turns. Failed or uncommitted output
is not presented as active memory.

Only propositions whose complete source-ID set is in the operation's source
lineage are eligible. Others are explicitly excluded, rather than scored as lost.
For repeated summaries, lineage only establishes eligibility; the proposition may
already have been lost in a parent summary. This evaluates survival of original
source-supported assertions, not just fidelity relative to the last summary.

Labels are `preserved`, `lost`, `contradicted`, `uncertain`, or JSON `null` for
unreviewed. A qualifier dropped from an otherwise correct sentence is not fully
preserved. Rationale remains text data. Source/output/propositions are hashed;
duplicate/missing/foreign review items and changed targets are rejected on scoring.
The report is required again when scoring to verify original event/snapshot binding.

Scored outputs are separate, self-contained version 1 artifacts with their own
`recording`, `evaluation_artifact`, annotations, provenance and metrics. They do
not modify the experiment report or enter active memory. Inspect their manifest
or evaluation with `tools/inspect_recording.py --artifact <sha256>` as with any
other content-addressed recording. The final evaluation can be inspected/calibrated
without the original report; re-scoring against a target requires the original.

Metrics include label counts, unreviewed count, proposition recall/bounds,
all-propositions-preserved per target, overall all-proposition recall, and
per-kind/per-depth summaries. Unknown/uncertain labels keep complete recall
unavailable. Bounds range from preserved/total to (preserved+unknown)/total.
A target's all-recall is 0 if any proposition is definitively lost/contradicted,
1 only when every eligible proposition is preserved, otherwise unknown.
No eligible propositions means unavailable, not vacuous success. These metrics
are separate from QA accuracy and do not detect every unsupported invention
outside the supplied proposition set.

### Imported judges and calibration

Human scoring requires an explicit annotator name/ID. To import existing model
annotations, use `score --evaluator evaluator.json` instead of `--annotator`.
No provider is invoked. The provenance schema is:

```json
{
  "type": "external_model",
  "model": "exact-model-name",
  "requests": [{
    "item_keys": [["target-id", "p1"]],
    "request": {
      "model": "exact-model-name",
      "messages": [{"role": "user", "content": "Exact rendered evidence-evaluation input"}],
      "temperature": 0
    },
    "response": {"content": "Exact returned content", "usage": null}
  }]
}
```

Every labelled item must link to a request; requests/responses become hashed
artifacts. Safe request kwargs, explicit settings, omitted provider-default labels
and reported usage completeness are retained. No credentials, client objects or
headers are accepted. `extra_body`, if supplied, supports only the thinking type.
Imported responses and label mappings are declarations, not independently verified
provider executions or automatic parsing of semantic decisions. Missing usage
stays unknown. Preserve a source-only diagnostic protocol; never send evaluation
propositions or questions back into memory formation.

```powershell
python tools/compaction_evaluate.py calibrate --reference human-fidelity.json --candidate model-fidelity.json --output calibration.json
```

Calibration requires the identical manifest and a human reference. It reports
paired/unpaired item counts, exact four-label agreement (including `uncertain`),
and a confusion matrix. Null labels are unpaired. This is descriptive agreement
on the supplied annotations, not proof of judge validity or a confidence interval.

## Paired campaign confidence intervals

```powershell
python tools/compaction_evaluate.py compare --left full-r1.json full-r2.json --right compact-r1.json compact-r2.json --vary retain_percent --resamples 10000 --seed 42 --confidence 0.95 --output paired.json
```

Left/right are two fixed conditions; each file is a repeat, not another percentage
inside a condition. Multi-run conditions need explicit unique
`compaction_campaign.repeat` values and matching repeat-ID sets. A single report
without campaign metadata is repeat 1. A resumed run can finish a replicate; a
resumed copy or frozen construction cannot count as another independent repeat.

The comparator requires stopped, fully archived runs and identical archived
dataset, selected questions/references/categories, ordered sources where formed,
reader/judge settings/prompts, tokenizer, code/dependencies and controls except
explicit `--vary` treatment fields. The default is `retain_percent`. Within a
condition, repeats must have identical controls. `modules` can be declared for an
architecture treatment; applicable formation fields may then differ, while
reader/judge/tokenizer identities must still match. Other differing applicable
controls must also be explicitly declared. Changing source scope or reader budget
is deliberately not silently accepted as a matched percentage comparison.
Mismatches fail; the tool never silently takes a question intersection.

Primary endpoint is question-weighted **end-to-end success over all selected
questions**. Missing/unjudged items count as operationally unsuccessful. Selected,
judged, missing and status coverage are reported; this is not an assertion that
unjudged predictions are semantically wrong. Judged-only accuracy is descriptive
and carries no interval in this output.

The versioned method reports right-minus-left percentage points and a percentile
interval. Each bootstrap draw samples conversations with replacement, then paired
repeat blocks within each sampled conversation, retaining all questions together.
The default is 10,000 draws and a 95% interval. `--seed` controls this local
resampling only, not provider generation. Fewer than two distinct conversations
produce no interval. One repeat can assess conversation sampling variability but
cannot estimate repeated-generation variability. Few conversations, selected
experimental conditions, multiple comparisons, and provider drift limit inference.
No p-value or general effectiveness claim is inferred automatically.

Outputs record input report hashes, treatment fields, matched manifest hash,
cohort/repeat counts, method/version/seed/draws and coverage. Reports need not
survive on their original filesystem paths, but retain them to inspect the
underlying recordings. All CLI outputs use new paths only: complete temporary
files are fsynced and atomically published without replacing an existing target.
The destination filesystem must support hard links; unsupported filesystems fail
explicitly instead of falling back to unsafe overwriting.

## Validation and limits

Tests use synthetic text/labels, exact algebra and mocked providers. They verify
bookkeeping, identity, denominator and resampling behavior, not compression or
judge quality. No automatic semantic judge, learned policy, protected raw-tail
architecture, monetary pricing model, GPU memory or remote FLOP estimator is
introduced. Human verification/imported annotations are still required to obtain
actual fidelity measurements. Existing result files are never rewritten.
