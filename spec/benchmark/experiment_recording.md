# Experiment recording contract

New runs retain a version 1 `recording` archive inside the established schema 2
LoCoMo report. The scoring protocol is unchanged. The [research, gap audit, and
pre-implementation design](../../plans/experiment_recording_2026-11-10.md) explain
the choices. Offline fixtures verify custody and accounting, not model quality.

## Ownership and format

`config` owns normalized controls. `recording_contract` identifies selection policy,
explicit input option names, category counts, unsupported seed control, and the
replay/timing scope. Existing dataset/config/prompt hashes remain compatibility
identifiers. Code identity includes working Python/tool source and requirements
hashes, Git revision/dirty state and installed dependency versions. No dataset
release name is inferred from a filename: archived content is authoritative.
Sweep repeat/campaign identity remains under `compaction_campaign` on resume.

```text
recording:
  version: 1
  layout: inline-run-owned-sha256-v1
  artifacts:
    <sha256 of canonical {kind,value}>:
      kind: <artifact type>
      value: <JSON payload>
```

A reference is exactly `{"artifact_sha256": "<64 hex characters>"}`. Canonical
hashing uses sorted keys, UTF-8, compact separators, and rejects NaN/infinity;
list order matters. Identical kind/payload pairs deduplicate within a run. Hashes
detect damage and establish identity; they are not signatures. Capture/read returns
detached data. There are no external artifact paths, shared blobs or bundles.

The archive owns exact payloads. Existing `memory`, `compaction_artifact`, and
diagnostic fields remain compatibility/inspection projections. In new reports the
legacy `compaction_artifact` envelope uses objects owned by the run archive; it is
not independently portable. Export the whole results JSON. A standalone
`Compaction.export_state()` includes its own archive for independent restoration.

## Capture points

| Artifact kind | Recorded content and boundary |
| --- | --- |
| `dataset`, `ordered-source` | Input dataset and chronological labelled ingestion entries; controls and omission counters identify one-shot source limits. QA annotations stay in the evaluation archive only. |
| `memory-state` | Pre-QA frozen state and partial formation checkpoints: ordered entries, deque capacities, summaries, vectors, facts/versions/provenance, revision/ID counters, pending buffers and recursive children. Explicit allowlists exclude services, credentials, locks and weights. |
| `compaction-source` | Exact ordered entries, rendered source, depth and ingestion counter before each operation. |
| `compaction-input`, `compaction-candidate` | Rendered compressor prompts and verbatim output for every returned attempt, captured before stripping, validation or cancellation. A transport failure without a returned body has no candidate. |
| `compaction-replacement`, `compaction-transaction-state` | Validated staged replacement, then actual committed or rolled-back state/counters. Accepted output can remain uncommitted. |
| `context-candidates` | Ordered packing candidates, including entries later omitted/shortened; hybrids retain per-component groups. |
| `answer-context` | Exact supplied text, selected entries, framing/messages, tokenizer/count, packing metadata and frozen memory link. |
| `provider-request`, `provider-response` | Safe actual request kwargs and returned ID/model/content/finish reason. Request ledgers own retries, explicit settings/default omissions, returned identity, usage, errors and timing. |
| `prediction`, `case-attempt` | Validated prediction linked to context/state/request/response; earlier failed or incomplete cases retained when resumed. |
| `chat-context`, `chat-request` | Live chat's answering state/context and each rendered ReAct request. Chat exports include the session archive; its legacy SDK retry policy is not the controlled benchmark ledger. |

Compaction events own parent/depth, source/output hashes, percentage/target,
before/after tokens and bytes, validation attempts, errors and commit status.
Repeated operations consume prior compacted state plus subsequent raw entries.
Staged operations in one write have explicit parent links even after rollback.
One-shot percentages independently ingest raw source; they never recompress
another percentage's result. Source lineage establishes ancestry, not semantic
fact survival.

Neither retrieval nor compaction receives an archive reader. Benchmark compaction
inputs contain conversation only, without future questions, answers, categories
or gold evidence. Pre-QA memory is frozen; QA is never written back.

## Usage, timing and storage

Formation, compaction, retrieval, answering and judging retain separate diagnostics.
Request ledgers count transport attempts and preserve returned usage details,
including cache/reasoning counts when available. Compaction requests carry event
and validation-attempt IDs; regeneration differs from a transport retry.

Missing usage remains unknown, including failed requests that may have reached
the provider. Complete totals require coverage; known recorded usage is a labelled
lower bound, never a monetary estimate. Enriched Compare Runs data adds
`overall.construction`: unique construction IDs, attempts, rebuilds, frozen reuse,
formation/compaction request usage and answering/judging coverage. Scope is this
report plus retained resume history; separate campaign files still need explicit
aggregation. Existing token/runtime metrics retain their documented campaign
amortization across questions.

Application wall time includes retries, backoff and recording/checkpoint overhead.
Per-request `provider_seconds` measures the SDK transport call, including network
wait, not GPU time. Audit overhead can be material and must be matched across runs.
Retrieval includes local model loading where existing diagnostics say so.

Storage measures have separate meanings:

- `stored_text_bytes`: active logical UTF-8 text, excluding metadata/vectors/audit.
- `snapshot_bytes`: inspection JSON including metadata and event references,
  excluding embedding arrays and audit payloads.
- `embedding_arrays_serialized_bytes`: numeric arrays at each component; not RAM,
  weights, provider cache or ANN index size. Stores use exact search.
- `archive_storage`: audit counts/canonical bytes at the memory checkpoint,
  preceding later QA artifacts; not final export size.
- `state_storage`: logical state serialization including configuration/children/
  vectors but excluding events/usage, separately from deduplicated frozen-state
  artifact bytes including audit references. Neither is resident RAM.
- Actual downloaded/local file bytes are export size. The offline inspector
  reports file bytes and current archive bytes. Whitespace affects file size only.

## Persistence, compatibility and resume

Source/request-start and response checkpoints preserve work before validation;
periodic formation checkpoints preserve partial logical state. After a hard
interruption, `started` means incomplete work with unknown usage. It is never
treated as a successful prediction. Callbacks run under the job RLock, preventing
older writes from finishing after newer ones. Atomic writes use unique temporary
files, flush/fsync and replacement. This is not a multi-file database transaction
or a guarantee against every power/filesystem failure; input/report files remain
separate atomic documents.

New-format resume validates hashes/references, dataset, selection/config, prompts,
policies, tokenizer, source/dependency identity and settings. Completed compatible
frozen state is reused for every architecture, including detached workers. Restore
checks architecture, field tree, controls, capacities and counters before applying
state; it never deserializes arbitrary classes or pickle. Missing/corrupt,
incompatible or stripped recordings fail explicitly, preserving original files.

Successful predictions retain original memory/context identities and request
ledgers. Judge-only resume reuses the prediction and original evidence, while
retaining prior case artifacts, requests and cumulative timing. A new-format
prediction without compatible frozen memory is rejected; it cannot silently gain
newly generated memory. Incomplete formation with no dependent prediction may
rebuild as a new construction attempt, retaining partial history.

Legacy reports remain readable/analyzable and keep their established resume path
with an explicit weaker-guarantee label. Their original stochastic state cannot
be recovered retroactively. Missing archives on declared v1 recordings are errors,
not automatic legacy downgrades.

## Portable workflow and inspection

1. Use **Export results**, **Saved runs → Export**, or **Export to Compare Runs**.
   These fetch `/api/benchmarks/<run_id>/export` with the full archive. An active
   run's export is a self-contained checkpoint; prefer the final export for a
   completed experiment. Imported-memory-only exports are inspection projections.
2. Copy the JSON to another machine or import it in Compare Runs. Import validates
   before writing. Renaming/deleting a run cannot damage independent copies. No
   sidecar or artifact bundle is required.
3. Validate/inspect offline without credentials, model loading or network:

   ```powershell
   python tools/inspect_recording.py path/to/results.json
   python tools/inspect_recording.py path/to/results.json --artifact <sha256>
   ```

4. GET `/api/benchmarks/<run_id>/artifacts/<sha256>` for a single hash-checked JSON
   object. It uses `nosniff`, without interpreting source text as HTML. Existing UI
   technical diagnostics expose references; text-content rendering stays escaped.
5. CLI resume needs the original dataset and compatible environment. New outputs
   refuse existing paths; updating an existing report requires explicit `--resume`
   of that same output. Keep a copy if both checkpoints are needed.

Normal benchmark polling omits `recording.artifacts` and says `payloads_omitted`.
That response is not portable and fails archive validation. Chat diagnostics also
omit archive payloads; chat Export includes them. Service credentials, headers,
environment variables and client objects are excluded. Source text itself remains
exact, so source data confidentiality follows the source.

Read-only browser-local imports retain their existing structural validation; they
do not verify SHA-256 objects. Server library imports, saved-run exports/resume,
single-artifact reads and the offline inspector perform hash validation. Use the
inspector when checking a downloaded or browser-local file independently.

Confirmed deletion uses existing stopped-run/lease checks and deletes only that
run's JSON, input copy, logs and controls. Inline archives cannot orphan shared
filesystem blobs or delete another run's objects.

## Limits and interpretation

Archives are lossless/unpruned. Repeated sources, candidates and partial snapshots
can greatly exceed active memory size. In-memory archives and whole-report atomic
writes suit bounded datasets, not unbounded campaigns. Browser imports retain the
32 MiB limit; larger files can be copied/inspected/resumed locally with the CLI.
There is no cross-run content store, retention policy or automatic old-data migration.

Weights, provider infrastructure/cache, dependency wheels and dirty source files
are not bundled. Vectors are stored exactly, but new query embeddings can vary
with unpinned model weights/runtime. Provider aliases/defaults may change and
immutable versions may be unavailable. The archive reconstructs recorded logical
memory, selected context, requests and observed outputs; it does not guarantee
identical stochastic provider outputs. Bodies that never returned cannot be
recovered and their usage remains unknown.

The default reader allowance remains 8,000 pinned MiniLM benchmark tokens.
Full-source percentage sweeps including 100% may explicitly need 40,000 for the
bundled dataset. These are controls, not established optima. Adaptive-policy
quality remains future empirical work. Offline fidelity annotations and paired
campaign statistics are now available through the separate
[compaction evaluation workflow](compaction_evaluation.md); actual labels and
provider-backed effectiveness evidence still require empirical evaluation.
No paid provider experiments were run for this implementation.

Evidence: `tests/test_experiment_recording.py` plus existing compaction, uncertainty,
lifecycle/recovery/deletion, context packing, imports, chat and frontend suites.
