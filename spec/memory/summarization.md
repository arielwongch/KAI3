# Rolling summary memory

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

Implementation: [Summarization.py](../../src/Summarization.py) and
`Benchmark.ingestion_batches`.

## Purpose

The module repeatedly replaces one summary with an LLM-generated update
based on the previous summary and the next group of turns.

## Stored data and write flow

1. The runner groups up to `summary_batch_size` turns (default 20), without crossing
   session boundaries. A batch normally contains at most 12,000 characters,
   including formatted labels and separators. A single oversized turn stays intact.
   Setting batch size to 1 gives one summary update per turn.
2. Join the batch texts with blank lines. Pass the current summary (or `(none)`)
   and this new text to the summarizer. Its prompt asks to retain important facts,
   decisions, preferences, names, dates, and context within `max_summary_tokens`.
3. Make one logical memory LLM call per batch, then enforce the token cap locally.
   If needed, retain a token-aligned prefix and append `\n[Summary truncated]`,
   counting the marker in the cap. If even the marker cannot fit, store an empty
   summary with `truncated=True`. There is no second compression call.
4. Replace the previous summary only after the new response is validated and
   capped. Retain the summary string and truncation flag; do not retain the
   original turns or earlier summary versions in the module.

## Retrieval

Retrieval ignores the query and returns either no entry for an empty summary
or one `MemoryEntry` with `type="summary"` and `truncated` metadata. There is no
ranking or embedding. The same final summary serves all QA questions. With the
validated cap no larger than the context allowance, a nonempty summary fits as
one candidate. Explicit finite candidate k is rejected.

## Limitations

Details lost during generation or truncation cannot be recovered from
this module. Summaries have no validated dialogue-ID attribution; seeing a turn
at ingestion does not establish evidence coverage. Batching affects generated
content and cost, so exports record batch settings and ingestion unit. Live chat
without a token cap uses the separate `summary_limit` character cap (default
10,000); that is not the benchmark summary-size rule.

## Interfaces and configuration

`MemoryFactory.create_memory_module("summarization", max_summary_tokens=2000,
tokenizer=tokenizer)` selects benchmark token-limited storage. The tokenizer
is required when a token cap is supplied. `summary_limit=10000` controls the
live-chat character-limited path. `summary_batch_size` belongs to the benchmark
runner rather than the memory factory. Record capacity and finite candidate k
are unsupported.

The [shared interface](interface.md) defines module calls and snapshots.
The benchmark applies [context packing](../benchmark/context_budget.md) after
candidate selection; storage and retrieval limits are independent.

## Failure behavior

A failed LLM call, non-string response, or failed token-cap calculation leaves
the previous summary unchanged and propagates an error. A successful empty
string response replaces it with an empty summary. Truncation is a reported
size-control outcome, not a failed write. Ingestion errors block the affected
conversation's pending benchmark questions.

## Verification

[Summary benchmark tests](../../tests/test_summary_benchmark.py) cover batching,
failed writes, and resume settings. [Controlled comparison tests](../../tests/test_controlled_comparison.py)
cover token caps, truncation markers, and rejected candidate k.
