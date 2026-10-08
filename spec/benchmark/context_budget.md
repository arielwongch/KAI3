# Memory context budget and packing

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

## Purpose and interfaces

The answer context uses one counting convention and packing policy across the
four memory conditions. `build_memory_context(module, query, token_budget,
tokenizer, retrieval_k=None)` calls the module's candidate API and returns a dict;
it is not an additional storage layer.

## Selection and rendering

The controlled benchmark uses `iter_context_candidates`, followed by
`build_memory_context`; it does not impose live chat's top-five retrieval limit.

1. Get candidates in the module's order, applying `retrieval_k` first. `null`
   considers all retained records. Summary accepts only an omitted/null candidate k.
2. Walk that candidate list and include each whole record if the resulting rendered
   context fits. Skip records that do not fit and continue within the same list.
   Do not fetch replacements from ranks beyond k.
3. Join included texts with `\n\n`. Window selections are reversed into chronological
   order; vector/fact selections remain in similarity order.
4. Count the exact rendered string, including labels and separators. Return its
   text, included entries, token/byte counts, candidate/included/omitted counts,
   truncation flag, tokenizer identity, and packing policy.

No dialogue or fact record is partially supplied. If candidates exist but none
fit, context is empty and `all_candidates_over_budget=True`. `omitted_count`
counts rejected candidates within k, not all stored records outside k.
`context_truncated` reports summary truncation; skipped whole records are reported
through omission counts instead.

Counts use the MiniLM WordPiece tokenizer, pinned to revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, with no special tokens or input
truncation. These are benchmark tokens, not exact provider tokens. Tokenizer
failure stops preparation rather than falling back to another counting method.
The allowance excludes the question and shared answer instructions. A separate
conservative whole-request byte-based guard applies to every condition; an
over-limit request fails without silent truncation.

## Configuration and stored result

`memory_context_tokens` defaults to 2,000. `retrieval_k=null` considers all retained
records; finite k is positive. Summary has no finite k or record-capacity option.
`max_summary_tokens` must not exceed the answer allowance. Defaults and supported
controls are listed in [lifecycle](lifecycle.md); unsupported explicit settings
are rejected, including null values for inapplicable controls. The CLI represents
all candidates as `--retrieval-k all` and unlimited supported storage as
`--max-stored-entries unlimited`.

The builder returns `text`, `entries`, `memory_context_tokens`,
`memory_context_token_budget`, `memory_context_bytes`, `candidate_count`,
`included_count`, `omitted_count`, `all_candidates_over_budget`,
`context_truncated`, `retrieval_k`, `tokenizer`, and `packing_policy`.
Tokenizer metadata includes ID, revision, loaded artifact SHA-256, counting
method, and `exact_provider_tokens=False`. Packing policy is
`whole-record-first-k-greedy-v1`. The benchmark moves text into
`supplied_context` and serializes included entries under `retrieved`.

## Failures and limitations

Invalid counts fail validation. Tokenizer loading/counting and module retrieval
errors propagate. The builder does not truncate turns/facts or invoke a second
LLM to compress them. Summary truncation occurs on write, as specified in
[summary memory](../memory/summarization.md).

The independent request guard uses UTF-8 bytes for message content plus 1,024
framing allowance, then adds reserved output tokens. Defaults are a 1,000,000
request limit and 8,192 maximum output tokens. This is a conservative estimate,
not the pinned benchmark tokenizer count or exact provider context measurement.
Legacy byte-valued `retrieved_token_budget` is not a v3 token allowance.

## Source and verification

[MemoryContext.py](../../src/MemoryContext.py) owns the tokenizer and builder;
[Benchmark.py](../../src/Benchmark.py) owns request guarding/configuration.
[Controlled comparison tests](../../tests/test_controlled_comparison.py) verify
whole records, separators, skip behavior within k, summary caps, and tokenizer
failure. Mocked tokenizer tests validate mechanics, not provider token equivalence.
