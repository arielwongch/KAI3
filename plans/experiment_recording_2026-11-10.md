# Experiment recording audit and design

Prepared 2026-11-10 (Asia/Hong_Kong), before implementation. Scope: local recording, offline synthetic tests; no paid experiments, commits, or changes to old results. Existing uncommitted compaction and benchmark work is preserved. No AGENTS.md was found in the repository (including hidden paths) or checked ancestor directories.

## Research and stopping rule

This review searched primary benchmark repositories/papers, compression studies, provider documentation, and reproducibility guidance. It followed benchmark references into reader/retriever separation, cost studies into cache accounting, and recent compression references into evidence-preservation diagnostics. Existing `compaction_research_2026-11-10.md` is background, not independently verified evidence for every paper it lists.

Verified findings, with review depth:

- [LoCoMo paper](https://aclanthology.org/2024.acl-long.747/) (abstract) and [author repository](https://github.com/snap-research/locomo) (README): long conversational QA evaluates multiple reasoning abilities. Record the actual data and selected questions, not merely the benchmark name. No inference about KAI3 accuracy follows.
- [LongMemEval author repository](https://github.com/xiaowu0162/LongMemEval) (README/evaluation instructions): distinguishes retrieval logs from reader logs and exposes history formatting, granularity, and top-k settings. Its README announces a cleaned dataset revision. Thus reader context, retriever settings, and dataset content identity are separate comparison dimensions.
- [ACON v3](https://arxiv.org/html/2510.00615v3) (method, analysis, limitations): optimizes compression guidelines using failure analysis and discusses compression overhead and cache dynamics. This motivates freezing prompts and recording attempts; it does not validate any KAI3 percentage.
- [Complexity Trap v3](https://arxiv.org/html/2508.21433v3) (cost analysis): summarization overhead and downstream trajectories contribute to total cost. Its coding-agent results do not transfer directly to LoCoMo; record construction and answering separately.
- [KEEP-Bench](https://arxiv.org/abs/2610.26827) (dated author abstract, 19 October 2026): successful QA can conceal unfaithful compression. Source lineage is therefore only ancestry, never evidence that a proposition survived.
- [Rate-distortion compaction view](https://arxiv.org/abs/2607.08032) (author abstract): identifies repeated compaction and future-query uncertainty as evaluation gaps. This is conceptual support for state lineage, not evidence for an optimal policy.
- [DeepSeek chat endpoint](https://api-docs.deepseek.com/api/create-chat-completion/) and [cache guide](https://api-docs.deepseek.com/guides/kv_cache/) (official documentation): usage can include cache counts; request omissions leave provider defaults in force. Preserve returned usage details and label omitted settings. No supported seed was found in the reviewed chat reference; do not invent seed control.
- [NeurIPS checklist](https://neurips.cc/public/guides/PaperChecklist) and linked [code guidance](https://neurips.cc/public/guides/CodeSubmissionPolicy) (reproducibility/settings/compute sections): disclose environment, settings, variability, and failed/preliminary work. Local artifact reconstruction is a narrower guarantee than identical remote stochastic output.

Stopping criterion: after the benchmark, compression-cost, evidence-preservation, provider-usage, and reproducibility search families, targeted follow-ups added rationale but no new required capture point or schema owner. This is design saturation for this implementation, not exhaustive coverage. Future adaptive-policy quality evaluation remains a proposal requiring held-out data and actual provider runs.

## Current gap audit

| Parameter/artifact | Current owner/location | Missing or unreliable behavior | Change |
| --- | --- | --- | --- |
| Dataset/version/selection/categories/order | Benchmark dataset_hash, config, question_manifest; conversation_entries | Hash alone cannot restore source; category selection lacks coverage summary | Archive exact dataset and ordered labelled source; record selected coverage and source policy |
| Repeat/seed | compaction_sweep campaign repeat | Campaign metadata not preserved through resume; seed unsupported | Preserve campaign identity; explicit unsupported/default seed label |
| Architecture/budgets/limits/summary caps | BenchmarkConfig, normalized config, module.inspect | Some defaults implicit; inspect omits vectors/counters/pending contents | Keep config authoritative; freeze explicit logical state plus effective inspect view |
| Compaction mode/percentage/trigger/scope | Compaction options/events | Events contain hashes/counts, no source/candidates | Separate content archive with exact source, all candidates, validated replacement, committed transaction state |
| Tokenizer/prompts/requests | MemoryContext identity, prompt hashes, RequestPolicy settings | Rendered requests not archived; omitted defaults ambiguous | Archive actual safe request kwargs; stable hash reference, returned IDs and defaults label |
| Model/provider/code/dependencies | AuditProvenance, Benchmark dependency_versions | Provider immutable revision unavailable; only Python sources hashed | Preserve limitation; expand source/dependency identity scope |
| Raw/facts/versions/provenance/embeddings | module.inspect, memory_identity | Hashes cannot restore arrays; pending contents/counters absent | Versioned explicit state codec, recursive children, no service objects/pickle |
| Answer context/framing/omissions | diagnostics supplied_context/retrieved/packing | No immutable snapshot link; hashes not retained for requests | Content-addressed context artifact linked to frozen memory before each prediction |
| Costs/timing/failures | Diagnostics, RequestPolicy, ResultAnalysis | Call counter differs from transport requests; judge resume replaces past failed work | Preserve request ledgers across attempts; unknown totals and known lower bounds; construction vs reuse label |
| Failure/cancellation/rollback | Compaction events and benchmark finally | Raw generated output lost; partial ingestion only saved at end | Archive before operation and immediately on response, transaction outcomes and periodic checkpoints |
| Resume | Benchmark.resume; compaction export_state only | Other architectures rebuild stochastically; old predictions can be associated with new memory | Reuse compatible frozen states for new contract; preserve original case links; reject damaged/incompatible recordings |
| Persistence/integrity | BenchmarkStore atomic_json; worker input/report | No artifact integrity validation; writes can finish out of order | Atomic run-owned archive, content hashes, serialize job writes under job lock |
| Exports/imports/downloads/deletion | app JSON exports/imports, delete_run_files | External sidecars would complicate ownership/portability | Single self-contained JSON archive; no shared filesystem objects; verify import/resume/export |
| Inspection/polling/HTML | chat diagnostics, workspace/Compare Runs | Large state payloads would inflate polling; rendering must remain escaped | Lazy JSON artifact endpoint; omit archive payloads in polling; use existing escaped diagnostics |
| Storage | storage_metrics stored text/snapshot counts | Logical memory, vectors, archive and export conflated | Add separately defined byte measures; serialized bytes are not RAM/index footprint |

## Concrete implementation plan and ownership

1. Add `ExperimentRecording.py`: versioned recording contract and canonical JSON SHA-256 objects, owned exclusively by one run. Layout is `recording.artifacts[sha256] = {kind, value}` inside the existing atomic report, with `{"artifact_sha256": ...}` references. This deliberately uses no external artifact files: missing references/corrupt contents are explicit errors, exports need no bundle, and deletion cannot orphan another run's data. Deduplication is within a run only.
2. Add an explicit allowlisted architecture state codec for raw entries, deque ordering/capacity, summary text/truncation, vectors, fact maps/versions and counters, pending buffers, hybrid children/config/usage. Restore into a newly configured module; never deserialize services, credentials, model weights, locks, or arbitrary classes. Configuration/code/tokenizer compatibility gates frozen reuse.
3. Capture dataset/source manifests, frozen pre-QA state, exact packed context and rendered request kwargs. Archive access is an audit facility, never an input to retrieval/compaction. The compactor receives conversation-only input; QA annotations exist only in the run archive.
4. Compaction owns transaction events and a detached archive for source/candidates/replacement/committed state. Every attempt retains unstripped candidate text before cancellation/validation. Mark rollback explicitly and retain accepted-but-uncommitted output. In a two-operation write, the second event must parent the staged first event even before commit.
5. New runs use a recording sub-schema while the established scoring protocol stays unchanged. Legacy reports remain readable; legacy resumes retain their existing path with an explicit weaker-guarantee label. New-contract resumes validate all references and compatibility, reuse frozen memory, retain original successful prediction/context identity and cost history. Incomplete formation may rebuild only if no prediction depends on it; retain partial artifacts as a separate construction attempt.
6. Serialize persistence callbacks under the job RLock. Checkpoint partial construction at progress intervals and compaction outcomes; regular atomic replacement provides process-interruption consistency (not a durable database transaction). The detached worker uses the same report contract. CLI must refuse a preexisting output unless explicitly resuming that output.
7. Polling omits the archive payload; export contains it. Add a bounded single-artifact JSON inspection endpoint, integrity checks on import/export, and a small offline verification/inspection CLI. Existing result analytics continue using their owned config/diagnostic fields, not competing copies of settings.

Storage growth: exact repeated sources and failed candidates may exceed active memory by orders of magnitude. Retention is intentional and lossless; no automatic pruning/GC. Deduplication avoids identical payload repetition. Whole-report atomic writes and in-memory archives are a bounded-dataset first implementation, not a scalable object database. Uploads retain the existing 32 MiB server limit; larger archives use local files/CLI. Polling should not return artifact payloads or duplicate compaction archives. Never report serialized bytes as resident RAM or provider cache size.

Acceptance: offline fixtures must establish source/candidate/replacement fidelity, independent percentage inputs and repeated parents, rollback/cancellation/retry unknown-usage handling, snapshot/context/request linkage, state restore across architectures, identity-preserving resume, explicit corruption/missing-object errors, portable JSON round trips, serialized background checkpoints and run deletion isolation, and legacy read compatibility. Run affected and full existing CI checks. Mock tests establish bookkeeping only; no model quality claim is authorized.

The default reader budget remains 8,000 pinned MiniLM benchmark tokens. Full-conversation comparisons (including 100%) may explicitly request 40,000. Neither value is an empirical optimum. Future adaptive policies must record decisions/observations without future QA leakage and be evaluated separately; they are not implemented here.

## Implemented result and validation

Implemented locally after the design above. The maintained [recording contract and
portable workflow](../spec/benchmark/experiment_recording.md) describe current
schema ownership, capture points, resume gates, byte definitions, transport/default
semantics and limits. No existing result was rewritten; no provider experiments,
commits or pushes were run. Preexisting uncommitted work was retained.

Files added for this task:

- `src/ExperimentRecording.py`: run-owned content-addressed JSON archive, integrity
  and prediction-link validation, allowlisted recursive state codec, compatibility
  checks, polling projection and state/archive byte accounting.
- `tools/inspect_recording.py`: offline archive verification and individual-object
  JSON inspection.
- `tests/test_experiment_recording.py`: 19 synthetic custody/portability/accounting
  tests, including the background-worker and request-start checkpoint paths.
- This research/audit/design and `spec/benchmark/experiment_recording.md`.

Existing files extended (including files already modified before this task):

- `src/Compaction.py`: complete source/candidate/replacement/transaction-state
  capture, staged parent lineage, early checkpoints and separate audit archive.
- `src/Benchmark.py`, `src/BenchmarkWorker.py`, `src/BenchmarkStore.py`: frozen-state
  reuse, prediction identity, partial/start/response checkpoints, serialized/fsynced
  atomic persistence, background compatibility and existing-output protection.
- `src/RequestPolicy.py`, `src/AuditProvenance.py`: rendered requests/responses,
  operation IDs, explicit/default settings, usage details, transport timing and
  expanded code/dependency identity.
- `src/MemoryContext.py`, `src/HybridMemory.py`: original packing candidates for
  omitted/shortened-entry inspection.
- `src/ResultAnalysis.py`: hash validation and separate construction/reuse/phase
  accounting while preserving established amortized comparison metrics.
- `src/ReAct.py`, `src/app.py`: chat context/request recording, portable exports,
  validated library import/download, small polling payloads and JSON-only artifact
  inspection. Existing UI rendering code remains unchanged.
- `tests/test_diagnostics_benchmark.py`, `tests/test_runtime_comparison.py`: update
  export/polling assertions and synthetic context fixtures for the strict contract.
- `README.md`, `plans/README.md`, `spec/README.md`, `PROGRESS.md`, `UPDATES.md`:
  navigation, usage and implementation evidence.

Final verification: **301 tests passed** with `python -m unittest discover -s tests
-v` using `DEEPSEEK_API_KEY=test-only`, `PYTHON_DOTENV_DISABLED=1`,
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`. This includes existing frontend
regression runners and 19 new recording tests. `node --check src/workspace.js`,
`node --check src/compare.js`, `git diff --check`, and the inspector CLI help check
also passed. Test output is in the ignored `instance/recording-regressions.log`.
These tests establish recording behavior only, not model effectiveness.

Material limitations remain explicit: unbounded archive growth and whole-report
checkpoint overhead; 32 MiB browser uploads; no cross-run artifact store; no bundled
weights/wheels/dirty source files; unpinned local query embeddings; unknown usage
for missing transport responses; weaker legacy replay; and browser-local structural
imports that require CLI verification for hashes. Reconstructing recorded state,
requests and observed outputs does not guarantee identical remote stochastic output.
