# Workflow DFS audit and fix plan — 2026-11-12

Status: F1–F10 implemented on 2026-11-12; verification recorded below.

The findings and proposed sequence below preserve the original audit. Their
source anchors and reproductions describe the pre-fix working tree. The user
subsequently authorized implementation; see the implementation record at the end.

Reviewed the current working tree, including existing uncommitted changes. No
application code, saved reports, or active workers were intentionally changed.
This is a source-level depth-first traversal of entry points, callees, state
mutations, branches, exceptions, and recovery paths; it is not an instrumented
execution of every possible provider/browser interleaving.

## Findings, ranked

P1 means incorrect agent behavior, memory loss, or loss of a usable answer.
P2 means recovery, measurement, validation, or usability errors.
All ten findings below have isolated offline reproductions. Existing tests pass;
these reproductions cover branches missing from that suite.

### F1 · P1 · ReAct fabricates observations instead of executing actions

Source: `src/ReAct.py:133–136`.

DFS: `/get` → `run_ReAct` → model response → action regex → append observation
→ next model request. The parsed action name is unused. Its argument becomes
the observation without any tool dispatch or execution.

Reproduction: a mocked response of `Action: lookup: forged tool output` makes
the next request contain `Observation: forged tool output`. No lookup ran.
This permits an answer to rely on a result invented by the answering model.

Fix: the current application exposes no actual tool registry, so use a direct
answer flow by default. Remove the action/observation instruction and synthetic
observation branch. If actual actions are required later, introduce an explicit
allowlisted executor and supply observations only from its returned results.
Do not merely rename the echoed argument as an observation.

Acceptance: action-shaped model output never becomes trusted execution evidence;
ordinary answers still work; bounded handling of invalid/empty output remains.

### F2 · P1 · Empty summary output erases existing memory

Source: `src/Summarization.py:44–56`.

DFS: summary write → provider response → string-type check → truncate/assign.
An empty string passes validation and replaces a nonempty summary. This affects
standalone summarization, Alpha, Windowed Summary, Delta, and Epsilon.

Reproduction: initialize the summary to a known preference, mock the provider
return as `('', 0, 3)`, then write a new entry. The summary becomes `''` and
inspection returns zero entries.

Fix: stage and validate a nonblank candidate before assigning it. Check returned
finish metadata where available and reject length-truncated/invalid responses;
retain the previous summary and count paid work on rejection. Keep the documented
local size-fitting policy explicit rather than treating it as provider validity.

Acceptance: empty/whitespace/invalid/truncated responses preserve prior state;
valid responses commit; wrapper windows, pending buffers and paired components
also retain their prior state when summary validation fails.

### F3 · P1 · A memory-write failure hides an already-generated chat answer

Source: `src/ReAct.py:120–131`, `src/ReAct.py:188–190`, `src/app.py:503–510`.

DFS: generate final answer → mark completed → write memory → extraction or
embedding error → outer exception marks turn error → `/get` returns only 503.
The useful answer exists in diagnostics but is absent from the chat reply.
Resending can incur another answer-generation charge.

Reproduction: mock a valid final response and make `module.write` raise.
Diagnostics retain `final_answer='Useful paid answer'` and paid tokens, while
the call raises and status becomes `error`.

Fix: split answer status from memory-write status. Return the completed answer
with an explicit memory-update warning and failed-write diagnostics. Retain the
original interaction for an explicit write-only retry; never regenerate the
answer to retry storage. Do not silently continue as though memory was updated.

Acceptance: answer succeeds plus write fails → visible answer, visible memory
warning, unchanged transactional stores, one answer request; a write-only retry
uses the original entry. Answer-generation failure still produces an error.

### F4 · P2 · First-request failures can permanently lock an uncreated chat

Source: `src/workspace.js:258–278`, `src/workspace.js:241–254`.

DFS: new chat → send → request rejected before session registration → catch sets
`started=true` → diagnostics returns 404 → `unavailable=true` → send disabled.
The user must abandon a chat whose server memory never existed. A network error
before request delivery can produce the same state.

Reproduction with the existing frontend harness: first `/get` returns 400 and
diagnostics returns 404. Result: `started=true`, `unavailable=true`, send disabled.

Fix: distinguish first-request rejection, successful server creation, and
ambiguous transport failure. A pre-creation rejection must leave settings and
retry available. For an ambiguous delivery failure, reconcile server existence
before deciding whether to initialize or require existing memory. Preserve the
lost-memory protection for previously confirmed sessions. If retrying an
ambiguous delivered turn, use a request ID to prevent duplicate writes/calls.

Acceptance: rejected initial request can be corrected and retried; lost existing
memory still blocks continuation; an uncertain request does not blindly replay.

### F5 · P2 · Ingestion cancellation is labelled as construction failure

Source: `src/Benchmark.py:879–898`, `src/Benchmark.py:1185–1196`.

DFS: cancel during memory provider request → `RequestCancelled` → generic
ingestion exception → mark all pending questions `ingestion_blocked` → save a
memory error → final status becomes `cancelled`. The case failure counts and
memory error then mix user cancellation with an actual broken mechanism.

Reproduction: cancel and raise `RequestCancelled` from an ingestion write.
Result: run status `cancelled`, case status `ingestion_blocked`, and case/memory
errors both say `Run cancelled.`

Fix: handle cancellation separately before ordinary ingestion failures. Preserve
partial construction, usage and request history; record an explicit cancellation
outcome and leave untouched questions not attempted (or explicitly cancelled).
Retain real ingestion errors and the existing failure-aware denominator policy.

Acceptance: cancellation during write, periodic flush and compaction produces
cancellation outcomes without fabricated mechanism failures; real extractor
failure still blocks dependent QA; partial state remains ineligible for frozen
reuse; prior paid predictions survive resume.

### F6 · P2 · Refresh leaves Compare Runs metrics stale

Source: `src/compare.js:78`, `src/compare.js:101`.

DFS: select file → cache report by pathname → another tab replaces/enriches the
same file → Refresh → fetch filenames only → render cached report. Deselecting
and reselecting also reuses the same cached object. The displayed metrics can
disagree with Download selected, which fetches the current file.

Reproduction with the existing comparison harness: load `run.json`, clear the
request log, call `refresh()`. Only `/api/results` is requested and the cached
report remains present.

Fix: explicit Refresh must reload selected reports and invalidate unselected
cached reports. Preserve selection and show per-file reload failures. Use a
generation token to prevent an older load from replacing newer data. A future
version/ETag contract can avoid unnecessary reloads, but is not required here.

Acceptance: replace a same-name file externally, refresh, and see new metrics;
reselection reloads invalidated data; failed refresh cannot appear as fresh data;
removed files leave selection; download and displayed metrics agree.

### F7 · P2 · Storage accounting omits nested long-term embedding arrays

Source: `src/Benchmark.py:155–175`, `src/WindowHybridMemory.py:13–19`.

DFS: record memory → `storage_metrics(wrapper)` → look for `_records`/`_facts`
on wrapper → find neither → report zero vector bytes. The function recursively
handles paired `components`, but not `long_term`/`window` children.

Reproduction: Beta with a one-entry window and two writes has a vector in its
long-term store. Wrapper embedding bytes report `0`; applying the same metric
to `beta.long_term` reports `13` with a tiny injected vector.

Fix: recursively report window and long-term storage and explicitly define
parent totals. Sum each child once; keep active text bytes, serialized vectors,
snapshot JSON, audit archive and resident memory as distinct measurements.
Review wrapper eviction metrics in the same change: direct deque replacement
does not increment the child window's eviction counter.

Acceptance: Beta/Gamma/Windowed Fact Store parent vector totals equal their child
totals; Alpha/Windowed Summary correctly have zero vectors; Delta/Epsilon/Zeta
continue to count each component once; archived payloads are not counted as
active retrieval storage.

### F8 · P2 · Dataset/selection validation accepts silent empty workloads

Source: `src/Benchmark.py:311–436`, `src/Benchmark.py:447–451`.

DFS: upload → validate recognized `session_N` keys only → normalize selection
→ create manifest → execute. There is no requirement for a recognized source
session or a nonempty final question manifest.

Reproduction: a conversation keyed `session1` instead of `session_1` is accepted
with a nonempty question manifest, but its source turns are silently ignored.
A valid category-4 dataset selected with categories `[1]` is accepted with zero
manifest entries and can finish without evaluating any question.

Fix: validate that the dataset has recognized session structure, reject malformed
session-like keys, and reject an empty selected manifest before launching a job.
Keep explicit question-only baselines available; source-shape validation should
not accidentally prohibit an intentionally empty baseline fixture. If dry runs
are useful, expose them explicitly instead of recording successful benchmarks.

Acceptance: typoed session names fail clearly; a selection matching no questions
returns 400 and creates no worker/checkpoints; normal numeric session ordering,
question-only controls, and supported dataset variants continue to work.

### F9 · P2 · A local checkpoint failure rewrites provider success as error

Source: `src/RequestPolicy.py:60–105`.

DFS: provider succeeds → store returned usage/response artifact → checkpoint
callback raises → broad provider exception handler rewrites request status to
`error` → caller receives no response. The final checkpoint callback may also
mask the exception originally responsible for failure.

Reproduction: a mocked provider returns one successful response with two tokens;
the callback raises `OSError('disk full')` after the response. There is one actual
provider call, but its ledger status becomes `error` while tokens remain `2`.

Fix: isolate the transport try/except from response recording and persistence.
Track provider outcome and checkpoint outcome independently. Stop/pause work on
durability failure, preserving the returned response in memory; do not silently
continue paid work or replay a successful transport as a retry. Recovery can only
reuse responses actually retained in durable artifacts; a failed disk write
cannot promise crash recovery.

Acceptance: failed preflight checkpoint makes zero provider calls; failed
post-response checkpoint preserves completed provider status, known usage and
the response; it records a separate persistence failure and makes no second
transport call; original exceptions are not masked by cleanup checkpoints.

### F10 · P2 · Terminal setup differs from the web application's configuration

Source: `src/TerminalInterface.py:10–15`, `src/TerminalInterface.py:73–81`,
`src/ProviderClient.py:14–20`.

DFS: launch terminal → default `.env` discovery → construct OpenAI client → parse
arguments. The documented setup creates `src/.env`, while terminal execution
from the repository root does not explicitly load that file. Even `--help`
constructs a credential-requiring client before argument parsing.

Reproduction: disable dotenv and remove the DeepSeek key from a child process,
then run `TerminalInterface.py --help`. Exit code is 1 with a missing-credentials
error, instead of argument help. No provider request occurs.

Fix: put terminal startup behind `main()`, parse arguments first, and use the
shared lazy provider client/configuration path. Route raw terminal requests
through the shared bounded request policy; handle transport errors/EOF without
leaving a half-added conversation turn or terminating the whole session.

Acceptance: credential-free `--help` succeeds; importing the module does not
start input or require credentials; configured terminal and web use the same
environment source; a failed raw request is recoverable and retains its metrics.

## DFS coverage map

The following lists traversal order and important branches, rather than just
listing files. Shared callees were reviewed once and then revisited for
entrypoint-specific configuration and error handling.

| Root workflow | Traversed path and branches | Result |
| --- | --- | --- |
| Startup/navigation | `app.main` → Flask routes → public asset allowlist → home/chat/benchmark/compare → shared shell/loading; lazy provider/tokenizer/models | No new correctness defect established; terminal differs (F10). |
| Chat creation/continuation | browser session restore → settings → `/get` validation → per-ID initialization lock → session registry → per-session lock → ReAct → diagnostics/response → browser save/inspector; 400/409/410/503 branches | F3/F4. Registry locks are released before slow session creation. |
| Agent loop | retrieve → render context → archive state/context/request → provider → final/action/invalid-format branches → iteration bound → memory write → diagnostics cleanup | F1/F3. Legacy chat generation also bypasses the bounded request ledger used by benchmark/memory calls; align it while fixing F1. |
| Manual chat compaction | validate percentage → lock session → bind collectors/archive → compact → stage/validate/commit or preserve original → record event and usage → inspector/export | No additional defect established beyond shared F3/F9 concerns. |
| Benchmark creation | UI dataset/default dataset → selection/options → `/api/benchmarks` → `BenchmarkJob` manifest/identities → active-run check → initial checkpoints → thread/detached launch | F8. Preserve the existing fixed eight-worker entrypoint policy. |
| Formation | ordered numeric sessions → session-bounded batching → factory → write/batch/flush/one-shot compact → request checkpoint → final snapshot/freeze → optional human review | F2/F5/F7/F9. Partial formation is recorded and excluded from successful frozen reuse. |
| Question evaluation | frozen conversation barrier → bounded pool → copied ContextVars → serialized retrieval → context admission/request guard → answer → save paid prediction → judge → score/evidence annotations → save → join all workers | No new defect established in pool isolation or no-QA-writeback behavior; checkpoint boundary has F9. |
| Stop/finalize | cancellation/fatal provider/ordinary case failure → stop submissions → join → case groups → failure-aware manifest denominators → efficiency → terminal checkpoint | F5; retain separate judged accuracy, completion and end-to-end success measures. |
| Review gate | generate review token → persist waiting state → thread event/detached token file → token validation → continue/cancel | No new defect established. |
| Persistence/recovery | freeze → immutable artifacts → SQLite commit → atomic JSON replacement → summary cache → lazy HistoryIndex → lease/fingerprint checks → exact-path lookup → retryable/unreadable/missing responses | F9 at caller boundary. Windows replacement retries and false-404 protections have focused passing coverage. |
| Resume | stopped/lease checks → authoritative saved input → identity validation → preserve paid predictions → restore completed frozen memory or rebuild eligible partial state → retry answer/judge → aggregate history | No additional defect established. Algorithm-changing fixes must preserve strict compatibility checks and keep old reports readable. |
| Delete run | UI confirmation → refresh exact run → stopped/thread/lease checks → delete run-owned sidecars/snapshot → remove registry entry | No new defect established; partial filesystem failure remains an explicit retryable outcome. |
| Results/export/library | portable export validation → optional enrichment → upload duplicate/replace/keep-both → guarded relative JSON path → atomic save → rename/delete/download | No new path-boundary defect established. Read/change races with external filesystem writers were not exhaustively stress-tested. |
| Comparison | load library → select/cache report → enrich metrics → allocate construction/answer runtime and usage → category filter/chart/table/copy → refresh/download | F6/F7. Missing usage remains unknown; summed parallel durations are labelled processing time. |
| Benchmark CLI | parse → load dataset/report → validate resume → exclusive output creation → shared execution → incremental checkpoints → portable final output | Shares F2/F5/F7/F8/F9. Interactive review is explicitly rejected in this CLI. |
| Campaign preparation/execution | validate percentages/options → freeze dataset/campaign → independent conditions/repeats → explicit execute → per-run checkpoints → final JSON | Shares benchmark findings; execution was not invoked in this audit. |
| Fidelity/campaign analysis | validate artifacts → source-bound propositions/targets → annotation/evaluator provenance → score/calibrate; paired cohort/config/code/repeat validation → clustered bootstrap → exclusive new output | No additional defect established; statistics/tests do not establish semantic memory quality. |
| Offline adjudication | match reports/dataset → select gains/regressions/unresolved plus stratified agreements → blind packet/private key → provenance/duplicate checks → summarize labels and denominators | No additional defect established; requires actual human labels for calibration claims. |
| Maintenance/CI | startup profiler, archive inspector, generated loading bundle, Windows console watcher; GitHub test workflow → syntax check → offline suite | Helpers inspected; credential-free terminal-help coverage is missing (F10). No hosted CI run was triggered. |

### Every memory architecture

| Mode | Write DFS | Read DFS and failure boundary |
| --- | --- | --- |
| No memory | no-op | empty candidates; benchmark legacy alias normalizes to explicit full-context/question-only controls |
| Sliding window | append → bounded deque eviction | detached newest-first packing candidates → chronological supplied context; live chat uses retained window |
| Summarization | prompt prior summary + new batch → provider → validate/fit → replace | single summary → detached fitting; F2 |
| Vector store | chunk whole turn → validate/normalize embeddings → dimension check → append → capacity eviction | query vector → maximum chunk cosine score → stable rank → whole original turns |
| Vector + reranker | same vector write | cosine shortlist → pinned cross-encoder windows → checked scores → whole-turn rerank → final k; failures surface rather than silently falling back |
| Fact store (chat) | user assertions/current snapshot → strict operation validation → stage add/replace/remove → deduplicate → embed changed facts → capacity → atomic commit | cosine shortlist → rerank; assistant text is context, not asserted fact input |
| Temporal facts (benchmark) | labelled speaker/source → validate references → stage version transitions/support → embed → capacity/link availability → commit; batch path resolves chronological handles and bounded repair | current/historical records render speaker/time/status → shortlist/rerank; strict source provenance |
| Alpha | stage recent window → summarize evicted prefix → swap window only on success | long-term summary + recent turns → shared framed budget; F2/F7 |
| Beta | stage window → embed evicted turn → swap on success | reranked archived turns + recent; F7 |
| Gamma | extract facts from every turn → swap staged window | current chat/versioned benchmark facts + recent; F7 |
| Windowed Summary | stage pending + recent → update every k → commit pending/window; benchmark final flush | summary + recent under framed budget; F2/F7 |
| Windowed Fact Store | stage pending + recent → chronological fact batch every k → commit; final flush | current/versioned facts + recent; F7 |
| Delta | snapshot logical child state → batched summary + individual vector writes → rollback both on failure | summary/vector reserved shares → whole-record spillover → summary fit; F2 |
| Epsilon | same transaction with summary + current/versioned facts | summary/fact shares/spillover; F2 |
| Zeta | same transaction with vector + current/versioned facts | two reranked pools → separate shares → stable spillover |
| Compaction | stage full active state → threshold/oversized-append or one-shot operation → bounded validated attempts → atomic replacement/rollback → lineage/events | complete active state, matching tokenizer, reader allowance guard; no secondary packing |

## Implementation sequence

1. **Protect memory and useful answers (F2, F3).** Add targeted regressions first,
   then candidate validation and independent answer/write outcomes. Update chat
   and memory specifications. Decide explicit write-only retry storage before
   presenting a retry control.
2. **Correct agent semantics (F1).** Implement direct answering with bounded
   invalid-output handling and the shared provider policy. Preserve public return
   compatibility or migrate callers/tests together. Avoid introducing a tool
   framework that the current product does not need.
3. **Repair recovery states (F4, F5, F9).** Add initial-session reconciliation,
   cancellation-specific formation handling, and separate transport/checkpoint
   outcomes. Include failures before and after a paid response. Keep durability
   failures explicit and preserve existing lease/Windows replacement protections.
4. **Make displayed measurements current and accurate (F6, F7).** Reload selected
   reports on refresh, invalidate stale cache entries, and add recursive storage
   accounting with explicit byte definitions. Recheck frontend/backend parity.
5. **Close validation and CLI gaps (F8, F10).** Reject accidental empty workloads;
   make terminal parsing/import credential-free and reuse shared configuration.
6. **Validate compatibility and update records.** Run the affected regression
   groups, then the complete offline suite and JS syntax checks once changes
   stabilize. Changes to prompts, memory transitions or metrics require reviewed
   identity/version handling. Do not whitelist algorithm changes merely to make
   old runs resume. Exported historical reports remain viewable. Already-running
   workers retain loaded code until clean stop/resume; do not interfere with them.

At the time of the audit, all phases were proposed. No provider experiment is required to
verify these defects. Real-model accuracy, semantic retention, latency and judge
calibration remain separate experiments after correctness fixes.

## Verification performed

- `venv/Scripts/python.exe -m unittest discover -s tests`: **362 tests passed**
  in 148.396 seconds. Existing frontend wrappers are part of discovery.
- `node --check src/workspace.js` and `node --check src/compare.js`: passed.
- Isolated mocked reproducers for F1/F2/F3/F5/F7/F8/F9; existing Node VM
  harnesses for F4/F6; credential-disabled child process for F10.
- No paid provider requests, model downloads, live benchmark start/resume/cancel,
  or browser visual acceptance were performed as part of this audit.
- The shell sandbox could not initialize because of a Windows directory-lock
  failure. Repository reads and offline commands used the approved execution
  fallback. Source configuration files and credentials were not inspected.

## Implementation record — 2026-11-12

- **F1:** direct chat answers use the shared bounded request policy. Unsupported
  action output never becomes an observation; invalid/incomplete output has a
  bounded repair loop and is not written to memory. The legacy return tuple and
  final-answer envelope remain accepted for callers.
- **F2:** summaries validate nonblank content, provider finish reason and the
  locally fitted candidate before committing. Wrapper pending buffers/windows
  and paired components retain their transactional behavior on failure.
- **F3:** completed answers are returned with independent memory-write status.
  Pending interactions have an explicit write-only retry endpoint and button
  (terminal: `/retry-memory`). New turns/manual compaction wait for the write.
  Retrying an already-successful write is idempotent; retry work has its own usage.
- **F4:** rejected initialization remains retryable. Uncertain requests retain
  their ID and payload; diagnostics can recover a lost reply. Same-ID/message
  submissions reuse the saved response under the session lock. This guarantee
  is process-local and does not recreate confirmed lost sessions after restart.
- **F5:** cancellation during ingestion, final flush or compaction records a
  cancelled partial construction, without manufacturing ingestion-blocked cases.
- **F6:** explicit comparison refresh reloads selected reports, invalidates other
  cached reports and suppresses older response generations. Failed reloads keep
  selection but remove stale displayed metrics and show the failure.
- **F7:** storage totals recurse through paired components and window tiers;
  vector bytes/chunks count children once. Window eviction counts advance only
  after a successful commit.
- **F8:** malformed source session structure and empty selected manifests are
  rejected before launch. An explicit empty conversation object remains available
  for controls. Old zero-question test fixtures now use selected questions that
  are rejected by the local context guard, retaining credential-free execution.
- **F9:** transport success remains completed when a local checkpoint fails.
  Separate checkpoint errors stop further paid work. Preflight failure sends
  nothing, and an error-checkpoint failure preserves the transport exception.
  Successful response artifacts/usage remain in memory; failed durability cannot
  promise recovery after a process crash.
- **F10:** terminal imports and `--help` need no credentials or input. Raw chat
  shares lazy provider setup/retries, commits only valid conversation pairs,
  handles failed requests and EOF, and retains attempt diagnostics.

Regression coverage is in `tests/test_workflow_fixes.py`, the frontend and
comparison harnesses, plus migrated existing tests for changed semantics. Specs
for chat, memory, benchmark lifecycle/recording, comparison and setup were updated.
No compatibility bypass was added for changed execution sources. Saved reports
and already-running workers were left untouched. Live model-quality/visual
experiments remain outside this offline correctness verification.

Implementation verification: the full offline suite passed **376 tests** in
181.950 seconds, including 14 new Python failure-boundary tests and the existing
frontend wrappers. The chat harness passed 45 cases; comparison refresh/failure/
stale-response checks passed. Both frontend scripts passed `node --check`, all
35 `src/*.py` files parsed, and `git diff --check` passed. No paid provider calls,
model downloads, live worker operations or visual browser acceptance were run.
