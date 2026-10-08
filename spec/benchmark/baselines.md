# Question-only and full-context baselines

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

## Purpose and configuration

These are separate reference conditions, both using the
[NoMemory component](../memory/no_memory.md). Neither accepts memory budget,
retrieval k, stored capacity, summary size, or fact-history controls. Both use
fresh requests with the same answer prompt/settings as memory conditions.

## Question Only (`question_only`)

The runner skips ingestion writes and supplies an empty conversation string to
`direct_answer`. The answer prompt renders `(No conversation supplied.)` before
the question. No conversation memory tokens are supplied, but instructions and
the question still consume provider tokens. Evidence recall is not applicable.

## Full Context (`full_context`)

The runner formats every turn using [lifecycle](lifecycle.md), then joins the
complete conversation with blank lines into a string outside the memory module.
Every question receives that transcript in session/turn order. Retrieval and
token packing are bypassed; the memory-context allowance does not apply.

Module storage metrics remain zero because the transcript is outside NoMemory;
the runner still uses RAM and sends conversation text to the answer model.
The memory review UI can show that transcript separately. Evidence coverage uses
all original dialogue IDs. This condition is a reference, not a guaranteed
accuracy upper bound.

## Compatibility and failure behavior

Legacy benchmark `no_memory` maps to `full_context` by default, or to
`question_only` with `no_memory_context="question_only"`. Contradictory explicit
baseline/context options are rejected. Live-chat `no_memory` continues to mean
no stored or retrieved memory and does not activate a transcript baseline.

Both conditions retain the [whole-request guard](context_budget.md). Over-limit
requests become `context_limit_exceeded`; there is no truncation or conversion
to retrieval. Historical saved `no_memory` labels alone do not prove full context:
ambiguous reports show a legacy unknown-input label and preserve saved metrics.

## Source and verification

[Benchmark.py](../../src/Benchmark.py) implements normalization and direct context
injection. [Controlled comparison tests](../../tests/test_controlled_comparison.py),
[binary benchmark tests](../../tests/test_binary_benchmark.py), and
[result import tests](../../tests/test_result_import.py) cover baseline behavior
and legacy reporting.
