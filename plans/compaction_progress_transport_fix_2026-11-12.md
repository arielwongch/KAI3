# Compaction stall: diagnosis and fix plan — 2026-11-12

Status: investigated and planned; no production code changed in this turn.
No application server, provider request, cancellation or resume was started.

## Verified state and evidence

The reported 75% one-shot compaction run has now stopped with status `completed`
and incomplete evaluation: 90 answers/judgments are retained, and the 10 selected
questions for `conv-47` remain ingestion-blocked. Its worker lease is released.
`completed` describes the runner finishing its selected work, not 100 successful
judgments. This attempt's failed compaction was not a WinError 1175 save failure.

- All 689 raw source entries were ingested before the failure.
- The source measured 36,786 benchmark tokens; the requested upper-bound target
  was 27,589 benchmark tokens at 75% retention.
- The compaction event ran for 356.25 seconds and was not committed.
- Five transport attempts failed with `APIConnectionError` caused by
  `RemoteProtocolError`: incomplete chunked response / peer closed the connection.
- Measured provider durations: 66.05, 62.45, 61.56, 61.52 and 61.55 seconds.
- `src/API.py` requests non-streaming, high-reasoning memory generation.
- `src/RequestPolicy.py` retries connection errors up to five times with backoff,
  using a 180-second SDK request timeout. These were remote disconnect errors,
  not recorded 180-second SDK timeout expirations.
- The inspection process has no configured proxy schemes or proxy environment
  variables. That does not establish the separate worker's complete network path.

## Failure chain

1. `BenchmarkJob._run` appends all original turns and updates the UI through
   `phase=ingestion`, ending at `turn_completed=689`.
2. It then calls `module.compact(reason='before_qa')` before allowing any QA.
3. No distinct compaction phase is published. The browser continues rendering
   `Writing turn 689 of 689` even though the remaining operation is an API call.
4. The compaction request uses `stream=False`; the application receives no
   incremental model activity. Retry attempt/backoff state is recorded in the
   request ledger but not shown in the main progress panel.
5. The remote connection closes around one minute on each attempt. The request
   policy repeats the same failed operation five times, accounting for the
   apparent six-minute stall. The consistent timing suggests a transport/gateway
   cutoff, but the saved records cannot identify which upstream component closed it.
6. When retries exhaust, the original memory is preserved and compaction is
   uncommitted. The selected questions are blocked rather than answered from
   incomplete or uncompacted memory. The other 90 saved cases remain valid.

Eight question workers cannot accelerate this stage: QA intentionally waits for
the single whole-conversation compaction to finish and validate.

## Implementation sequence

### 1. Accurate progress and liveness first

Change `Benchmark.py`, request progress hooks and `workspace.js` to distinguish
turn ingestion, compaction, waiting for provider output, receiving output,
validation, retry backoff and checkpoint saving.

- At 689/689, show `Compacting conversation`, not `Writing turn`.
- Show transport attempt N/5, elapsed operation time, time since last received
  data, last network error and scheduled retry delay.
- Keep reasoning activity distinct from final memory output. Empty final content
  while the model is thinking is not automatically a dead request.
- Emit throttled metadata-only heartbeats. Do not freeze/copy the memory archive
  or synchronously checkpoint every token/chunk. Preserve durable request-start,
  final-response and paid-prediction boundaries.
- Keep progress honest: ingested-turn completion does not imply completed
  compaction or completed QA. Do not invent a generation percentage/ETA.

### 2. Stream only compaction transport and assemble the final response

Implement controlled streaming aggregation in `RequestPolicy.py`, enabled through
the compaction-specific memory request options. In `API.py`, merge options once
instead of supplying both hard-coded `stream=False` and a duplicate override.
Leave ordinary answering, judging and other memory calls unchanged initially.

- Send the same source, prompt, model, reasoning effort, retention and output
  limits; change transport rather than the benchmark condition.
- Consume SSE through the SDK and assemble only final-content deltas into the
  candidate memory. Reasoning deltas can signal activity but must not become
  memory text or retrieval inputs.
- Handle usage on the terminal content/finish chunk. Do not assume a separate
  usage-only chunk or require a finish chunk containing new text.
- Return the same completed response interface expected by existing callers,
  preserving model/response ID, finish reason and token accounting.
- Record first-data, first-content and last-data times and transport mode.
  Measure provider time through the end of stream consumption, not merely until
  the SDK returns its stream object.
- Streaming can provide activity and reduce opaque buffering; it is not proof
  that an upstream one-minute cutoff will disappear. Validate that separately.

### 3. Retry, cancellation and commit safety

- Retain the existing bounded retry cap initially. Add observable inactivity and
  overall elapsed bounds; do not blindly increase the 180-second timeout to fix
  an earlier remote disconnect.
- On stream failure, archive any partial response as diagnostic evidence, keep
  usage unknown when it was not returned, and discard partial candidate memory.
- Close the stream on cancellation and during exception cleanup. Stop between
  chunks; bound blocked reads so cancellation cannot wait indefinitely.
- Retry the whole original compaction request. Do not concatenate candidates
  from different attempts or continue a stochastic partial response implicitly.
- Commit only a complete, nonempty, normally finished candidate that passes the
  existing target-token and state checks. Preserve transactional rollback.
- Keep the reader's 8,000-token allowance and provider output limit explicit.
  Benchmark-token targets and provider output tokens are different units. Do
  not silently lower retention, truncate memory or switch models to hide failure.
- Keep completed cases immutable. Resume only the unfinished `conv-47` work;
  retain earlier failed-attempt evidence and cumulative costs.

### 4. Provenance and rollout compatibility

Capture streaming options in request artifacts/settings. Preserve original
frozen state, source and prediction identities. Transport changes affect the
strict source/request compatibility gates, so implement an explicit audited
migration for affected files rather than disabling source/model validation.
Never reinterpret an interrupted stream as a completed recorded response.

Add a concise network-disconnect explanation in the run report and distinguish
completed-with-ingestion-errors from complete answer/judge coverage. An optional
later optimization may restore a verified full raw-ingestion checkpoint before
retrying compaction, but must never treat it as QA-ready frozen memory.

## Verification and acceptance criteria

Use offline fake streams for:

1. Long thinking activity followed by final text; progress leaves ingestion.
2. Terminal finish/usage on the final content chunk, empty deltas and keep-alives.
3. Disconnect before any content and after partial content; no state commit.
4. Retry succeeds; only the successful complete candidate is accepted.
5. All five attempts fail; original memory and all 90 successful cases survive.
6. Cancellation during streaming and retry backoff closes resources and stops work.
7. Truncated/empty/oversized outputs fail the existing validation rules.
8. Metadata heartbeats do not create per-token memory snapshots or large writes.
9. Saved artifacts, usage uncertainty, exports and resume validate across transport
   versions; the eight-question bound and conversation barrier remain unchanged.

Run the existing offline suite after implementation. A small paid live probe,
only with explicit authorization, can then compare stream/non-stream transport
from the same worker environment. Record durations and response/request IDs,
without exposing credentials or proxy addresses. Do not automatically rerun the
entire 100-question benchmark for diagnosis.

## Authoritative transport references

- [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/):
  streamed SSE deltas, termination and final-chunk usage/finish semantics.
- [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/):
  separate reasoning and final-content fields and streaming examples.

The exact remote cutoff remains unproven until controlled transport diagnostics.
The hidden compaction/retry stage and its misleading UI label are established
directly by the repository code and saved run records.
