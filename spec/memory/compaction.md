# Compaction memory

Implemented locally 2026-11-10. Research and future experiment methodology:
[proposal](../../plans/compaction_research_2026-11-10.md).

`compaction` replaces the complete active memory with an inspectable text summary
using the existing DeepSeek memory API. It is not OpenAI's native encrypted
compaction. It supports arbitrary retained percentages and one-time or repeated
operation. No adaptive controller or effectiveness result is included.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `retain_percent` | 50 | Finite number greater than 0 and at most 100; booleans rejected. |
| `compaction_mode` | `one_shot` (chat UI/terminal select `repeated`) | One-time before benchmark QA, or repeated during writes. One-shot chat is manual only. |
| `compaction_trigger_tokens` | 2000 | Repeated-mode active-memory threshold, independent of percentage. |
| `compaction_source_entries` | null | One-shot source: all entries, or the last N complete entries. Repeated mode rejects a finite source cap. |
| `memory_context_tokens` | 8000 | Reader allowance, independent of trigger and percentage. |

Factory callers may inject `tokenizer` and `compressor`. The latter has the same
`(system_prompt, input) -> (text, latency, total_tokens)` interface as `API.call_api`.
Shared factory `extractor`/`embedder` injection is ignored; there is no embedding
or retrieval component. `retrieval_k`, summary caps, and window-size controls do
not apply.

The versioned renderer joins entries with two newlines, without hidden labels.
Let N be the complete rendered memory count under the pinned benchmark tokenizer:

`target_tokens = floor(N * retain_percent / 100)`

The complete replacement must fit this target. Actual retained percentage is
`100 * after_tokens / before_tokens`. This excludes the fixed system prompt and
new question. Benchmark wordpiece counts are not provider-billed token counts.
100% preserves memory exactly and makes no compressor call. Empty memory is also
a no-op. An infeasible tiny target fails rather than silently raising the budget.

## Lifecycle

One-shot benchmark ingestion stores raw chronological turns, optionally keeping
only a declared latest-N window. It compacts once after ingestion and uses that
same state for all questions. No question, answer, category, or gold evidence is
given to the compressor. Separate percentage runs independently rebuild from raw
input; they do not compress each other's outputs.

Repeated mode checks a staged append. If adding a complete turn would exceed the
trigger, it compacts the existing state, then appends that turn. If the new turn
still will not fit, it may compact the combined staged state once under an
`oversized_append` event. That operation validates and retries against the smaller
of the percentage target and trigger, recording `acceptance_limit_tokens`
separately from the percentage's `target_tokens`. If no complete candidate fits,
the entire write rolls back. There is no unbounded fit loop. Subsequent compactions see only the
previous summary and newer raw turns, with no hidden raw-history retrieval.
Blank and explicitly incomplete entries do not advance ingestion. There is no
forced final partial-batch flush in repeated benchmarks.

The 100% repeated reference never frees space. It remains uncompressed and is
subject to the reader/provider guard; it is not silently converted to a sliding
window. Use matching source prefixes that fit, or a separate full-context arm.

The prompt preserves attribution, names/numbers/dates, chronology, changes versus
corrections, preferences/constraints, decisions, uncertainty, task progress, and
unresolved work. Structural validation is not a semantic-fidelity guarantee.
Generation uses a 90%-of-target requested text allowance and a 16,384 provider
output cap, which can include reasoning. The fully rendered output is measured
after generation. Empty/non-text/incomplete/over-budget output gets at most three
total generation attempts (the first call plus two retries), fixed in code with
no user override. Over-budget retries report the measured count and reduce the
requested allowance using the observed overshoot plus a safety margin. Incomplete
responses also reduce the requested allowance. Each attempt uses the unchanged
original source, never a rejected summary. The hard target and configured retained
percentage stay fixed; text is never sliced to manufacture a passing result.
An empty response with an incomplete finish reason also reduces the allowance.
Nonempty incomplete candidates retain their measured token count for diagnostics
but cannot be accepted. A failure to archive a returned candidate preserves known
usage and stops the benchmark as a durability failure rather than sending more
paid requests to later conversations.
Checkpoint callbacks are also fatal on persistence failure. Transaction-state
archiving is part of the commit boundary: a failure restores the original entries,
depth and counters, and no event is published as committed until all transaction
snapshots have been archived.
Exhaustion reports the rejection reason and final measured count, preserves the
committed state, and blocks QA for that conversation. Provider transport retries are separate
and remain in the shared request ledger. A conservative 1,000,000-token envelope
counts input UTF-8 bytes plus prompt/framing/output reserves before compression.

Failure or cancellation preserves committed active entries, counters, and depth;
attempt events and their costs remain recorded with `committed=false`. A lock
serializes retrieval, inspection, manual compaction, and writes. Chat's session
lock also serializes complete chat requests against manual compaction.

## Context and diagnostics

Compaction supplies the complete active state. It never uses the generic summary
fitter or silently drops a raw turn to satisfy the reader budget. Exceeding the
allowance fails with a message to raise the allowance or compact further. For a
pure percentage study, ensure the uncompressed reference and every replacement
fit the same reader allowance; the default 8,000 tokens may be insufficient for
a complete conversation. Use an explicit 40,000-token reader allowance for the
current bundled full-conversation percentage sweep including its 100% reference.

Inspection contains active entries, configuration, peak committed active tokens,
ingestion/omission counters, depth, and detached event records. Events record
source/output hashes, parent, source IDs, raw/compressed counts, target/actual
counts and percentages, reasons, byte sizes, attempts, response metadata, usage,
validation results, timing, and commit status. Source IDs are lineage only;
they do not prove the corresponding facts survived. Evidence recall is therefore
left unavailable for compacted summaries.

Events are not reader entries. Logical stored text counts active memory only;
serialized snapshot sizes include audit metadata. Exports additionally contain a
hashed frozen artifact, so export bytes are not equal to active-memory storage.
Missing usage remains unknown, including failed requests. Provider cache and
reasoning usage details are retained when returned. Existing analysis counts
formation plus answering and reports judging separately.

Benchmark resume reuses a successful frozen compaction artifact for unfinished
questions. Its source conversation hash, configuration, tokenizer, prompt,
renderer/policy, and model settings must agree. Original ingestion cost remains
in previous builds; reuse adds preparation time but no new compaction calls.
Invalid artifacts block ingestion instead of silently producing a new memory.
Failed original ingestion may be retried from the raw source as a new build.
The exact audited migrations from the original two-attempt compactor and first
three-attempt repair to the audited retry repair permit frozen-state reuse; exports retain previous code
identities and all original ingestion costs. Other execution-source changes still
require matching identities.

Compare Runs labels configurations and exposes requested percentage, mean actual
percentage per committed event, compaction time, and logical compaction attempts
on the scatter axes. Time/attempts include all recorded builds, not just current
snapshots, and retain whole-run scope under category filtering. Mean actual
percentage is not an estimate of information retained from the original history.

## Using the feature

Select Compaction in Chat or Test Benchmark. Chat settings lock after the first
request; **Compact current memory** has a separate editable percentage for a
manual operation. The diagnostics export includes manual-operation costs.

```powershell
python src/Benchmark.py --dataset data/locomo/locomo10.json --output instance/compaction-35.json --modules compaction --retain-percent 35 --compaction-mode one_shot --compaction-source-entries 50 --memory-context-tokens 8000
python src/TerminalInterface.py --memory-module compaction --retain-percent 35 --compaction-mode repeated --compaction-trigger-tokens 2000 --memory-context-tokens 2000
```

Both commands above make provider calls during use. Terminal compaction supports
`/compact 25` (or `/compact` for the configured percentage). Its `metrics` command
prints the detached memory snapshot and recorded operations; compaction mode also
prints its accounting with each operation.

Prepare a sweep without provider calls, using a new output directory:

```powershell
python tools/compaction_sweep.py --dataset data/locomo/locomo10.json --output-dir instance/compaction-study --percentages 100 75 50 35 25 15 10 5 --reader-tokens 8000 --source-entries 50
```

The helper freezes the dataset and source hashes and writes independent
conditions to `campaign.json`. `--repeats N` creates repeated builds. Add
`--execute` when intentionally creating a new paid campaign. Existing output
directories are rejected to preserve prior experiments. It does not select an
optimal ratio, calibrate a judge, or train an adaptive policy.

Implementation: [Compaction.py](../../src/Compaction.py). Offline coverage:
[test_compaction.py](../../tests/test_compaction.py), frontend state tests, and
comparison UI tests. Real-provider fidelity, quality/cost curves, and optimal or
adaptive settings require the separately planned matched experiments.
