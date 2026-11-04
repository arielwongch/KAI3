# Windowed fact store failure investigation and fix plan

Investigated 2026-11-04. Implementation follow-up: stable batch handles, compact
state, bounded validation repair, private failure artifacts, extraction budgets,
and report/resume policy identity are implemented locally. Provider-backed
verification remains outstanding; no new benchmark was launched.

## Saved-run evidence

Latest saved benchmark: `instance/benchmark_runs/b2a14abb-928c-48b5-b870-2e08178c4aa9.json`.
The run selected only `windowed_fact_store`, versioned facts, a 10-turn window,
unlimited storage, 10 conversations, and 10 questions per conversation. Memory
requests used `deepseek-flash`, thinking enabled, and high reasoning effort.
SHA-256 hashes of the current API, temporal store, window wrapper, request policy,
and benchmark code match the source identities saved with this run.

All 100 cases are `ingestion_blocked`; no answer or judgment was generated.
Run status `completed` means all cases were resolved, including blocked cases.
It does not establish a successfully evaluated fact store or zero answer accuracy.

| Sample | Saved ingestion error | Turns accepted before failure | Last successful provider response: input tokens |
| --- | --- | ---: | ---: |
| conv-26 | Connection error. | 49 | 17,148 |
| conv-30 | Unknown or repeated target version | 9 | 2,200 |
| conv-41 | Expected one ordered operations result per batch turn | 189 | 191,133 |
| conv-42 | Unknown or repeated target version | 9 | 2,083 |
| conv-43 | Expected one ordered operations result per batch turn | 219 | 213,585 |
| conv-44 | Expected one ordered operations result per batch turn | 289 | 270,480 |
| conv-47 | Expected one ordered operations result per batch turn | 519 | 492,582 |
| conv-48 | Target must be a current version of the same speaker | 539 | 442,665 |
| conv-49 | Unknown or repeated target version | 9 | 2,242 |
| conv-50 | Expected one ordered operations result per batch turn | 459 | 559,402 |

For validation failures, the last successful provider response is the extraction
that the application rejected. For conv-26, it precedes five failed transport
attempts. Accepted-turn counts include pending recent entries: a failed tenth
write leaves the previous nine pending entries intact. All failures occurred on
regular batch boundaries, before final flushing and QA.

## Root cause and limits of the evidence

The primary failure mechanism is the LLM/Python temporal batch contract in
`src/TemporalFactStore.py`, not retrieval or context packing. Nine conversations
received responses that failed its shape or state-reference validation. One
conversation independently exhausted the connection retry policy.

1. **The model must simulate Python's ID allocator.** `TEMPORAL_BATCH_PROMPT`
   permits later turns to reference newly created sequential `version-N` IDs.
   Python allocates those IDs while applying earlier operations, including exact
   deduplication, confirmations, status transitions, and capacity eviction. A
   mistaken allocation prediction can make later references unknown, point at
   another speaker, or point at a non-current version. The initial batches of
   conv-30, conv-42, and conv-49 already fail target validation with an empty
   starting store: prompt growth cannot explain those early failures.
2. **The prompt contains competing output/state instructions.** The batch prompt
   concatenates the single-turn prompt, which demands an `operations` envelope
   and supplies an empty-operations fallback, with instructions demanding a
   `turns` envelope and one result for every input. Single-turn wording limits
   references to supplied versions; batch wording permits earlier-turn additions.
   Five responses fail the outer shape/count check. This error combines several
   conditions, so the saved message cannot distinguish a wrong envelope from a
   missing result or another shape defect.
3. **The extraction payload grows unnecessarily.** Every request serializes all
   retained versions with full provenance metadata, repeated source text, source
   metadata, and observations. There is no extraction-specific token budget.
   The QA memory budget of 2,000 tokens does not apply here; the answer output
   setting of 8,192 is also not passed by `API.call_api` to memory requests.
   For conv-50's 1,313 retained facts, the serialized versions occupy 1,755,909
   characters; IDs, texts, speakers, and statuses alone occupy 201,445 characters
   using the same JSON serialization. This is evidence of payload overhead,
   not proof that reducing context alone will fix the failures.
4. **A single invalid response aborts ingestion.** Application validation occurs
   after `completion` returns. The request policy retries transport/provider
   errors, not invalid extraction results. Correct atomic rollback preserves the
   pending window and store; the benchmark then blocks that conversation's QA.
   This explains why 10 ingestion exceptions yield 100 blocked cases.

The saved artifacts contain request settings, response IDs, token usage, and
timings, but no raw extraction responses, finish reasons, failing dialogue IDs,
operation indexes, or offending references. Consequently, the precise malformed
operation for each sample, the exact cause of the shape/count failures, and any
provider truncation cannot be reconstructed. Sequential-ID drift is a reproduced
design failure, not a proven reconstruction of an individual saved response.
The connection error has no saved underlying exception chain; its network cause
is undetermined. Increasing reasoning effort is not an evidence-backed fix:
this run already used high effort with thinking enabled.

## Proposed implementation sequence

1. **Make extraction failures replayable.** Capture a private local diagnostic
   artifact for failed batches: prompt/protocol identity, compact input snapshot,
   input dialogue IDs, raw response, finish reason, request ID, token usage, and
   a structured validation failure with turn index, operation index, reference,
   and reason. Keep raw conversation data out of ordinary console/UI messages.
   Retain transport exception type and cause chain. Preserve the extractor's
   existing three-value return contract or version it explicitly.
2. **Replace predicted numeric IDs with explicit batch-local references.** Give
   each add/replacement an explicit unique result handle. Later turns may target
   those handles; Python maps them to real version IDs after allocation and
   deduplication. Existing versions remain explicit stable references. Validate
   unique handles, prior-turn visibility, actual speaker ownership, current
   status, and retained capacity. A deduplicated addition maps its handle to the
   surviving existing version. Reject unknown/forward references and references
   to evicted records. Resolve supporting references through the same mapping.
   Keep the existing single-turn contract and public stored numeric IDs intact.
3. **Use a standalone batch prompt and compact state schema.** Specify exactly
   one output envelope and one ordered result per input dialogue ID, including
   empty turns. Describe pre-turn validation and chronological state transitions
   explicitly. Send only fields extraction needs: stable ID, assertion text,
   speaker, status, and minimal temporal context where relevant. Keep full
   provenance and historical records in Python; do not remove stored history to
   shrink prompts. Measure token savings and ensure dates/history interpretation
   survive compaction.
4. **Bound extraction and recover without weakening validation.** Add explicit
   extraction input/output budgets and inspect finish reasons. Initially use a
   compact complete state rather than an unmeasured retrieval shortlist, which
   could conceal correction targets. If it still exceeds the input budget,
   report a precise extraction budget error; do not silently truncate facts.
   Allow a small bounded validation-repair retry from the unchanged starting
   snapshot with the structured error. Revalidate and stage the entire response
   before committing either tier. Never fill missing turns with assumed no-ops,
   silently skip bad references, or answer from incomplete memory. Do not split
   batches into extra extraction calls without an explicit protocol change.
5. **Version behavior and report outcomes clearly.** Update prompt and extraction
   policy identities, budgets/retry settings, resume compatibility checks, and
   the periodic-memory spec. Record repair calls and their usage. Distinguish a
   run that finished with ingestion errors in the report/UI without changing
   existing case-state scoring semantics. Preserve the old run for diagnosis;
   validation of the new contract should use a new run identity.

## Verification and acceptance

- Existing `test_periodic_memory.py`: 13 offline tests passed during this
  investigation. They cover atomic rollback and basic chronological references
  but supply already-valid numeric IDs; they do not test model ID prediction.
- An offline deterministic reproduction supplied duplicate additions in D1/D2
  and a D3 confirmation targeting predicted `version-2`. Deduplication meant only
  `version-1` existed; the store raised the saved `Unknown or repeated target
  version` error and rolled back records, revision, and ID counter. A valid JSON
  single-turn envelope also reproduced the saved outer batch-shape error.
- Add offline regressions for duplicate-handle resolution, same-speaker and
  current-state checks, status changes, capacity eviction, supporting references,
  unknown/forward handles, missing/reordered turns, repair exhaustion, truncated
  responses, embedding failures, and unchanged pending/window/store state on
  terminal failure. Preserve single-turn behavior and one-call normal batching.
- Test prompt/state compaction on this saved cohort, including the long conv-50
  state; verify token counts, preserved necessary fields, and no provenance loss
  in stored records. Test extraction budget errors independently of QA budgets.
- Before repeating the full study, run ingestion-only checks on the three
  first-batch failures and one long conversation, with diagnostics enabled.
  Then require successful full ingestion/flush of all 10 conversations before
  evaluating answer quality. Provider-backed verification remains future work.

Open decision: the exact extraction token budgets should be chosen from measured
compact payloads and the configured provider's verified limits. No provider
limit or truncation cause was assumed in this investigation.
