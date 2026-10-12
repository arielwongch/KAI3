# Hybrid memory: delta, epsilon, and zeta

Implemented and checked against source on 2026-10-12. These modes are available
in live chat, the memory factory, benchmark UI/API, and benchmark CLI.

| Mode | Independent components |
| --- | --- |
| `delta` | `summarization` + `vector_store` |
| `epsilon` | `summarization` + `fact_store` |
| `zeta` | `vector_store` + `fact_store` |

## Construction and configuration

`MemoryFactory.create_memory_module(mode, **options)` returns a `HybridMemory`.
Each component receives original conversation input; neither consumes the
other's generated representation. Vector memory retains original interactions;
fact memory independently extracts assertions. Embedding services can be shared,
but their stored records are separate.

`hybrid_shares` maps both component names to positive fractions summing to 1;
defaults are 0.5/0.5. `memory_context_tokens` defaults to 2,000. The benchmark
uses its existing pinned tokenizer; live hybrid chat now uses that tokenizer too
(including its first-use download). `component_options` may map either record
component to `retrieval_k` and/or `max_stored_entries`. Each accepts a positive
integer or null for all/unlimited. Unknown components/options are rejected.

Common `retrieval_k` and `max_stored_entries` are defaults for each record
component, not a combined count across stores. Per-component settings override
them, including explicit null. Benchmark k defaults to all; live chat uses five
per record component unless overridden. Capacity defaults to unlimited. Summary
is independent of record k/capacity and accepts its existing size settings.
Benchmark `max_summary_tokens` defaults to the total allowance and cannot exceed
it; the supplied summary can be shortened further during context packing.

Chat `/get` accepts these settings in `memory_options`, fixes them for the
conversation, and returns 409 for attempted changes. The UI exposes shares,
context allowance, and optional per-component JSON controls before the first
message. Benchmark controls use the same JSON representation. CLI flags are
`--hybrid-shares` and `--component-options`, each taking a JSON object.

## Writes, batching, and failure behavior

`write(entry)` is an atomic hybrid transaction. `write_batch(entries)` updates
the summary once with joined original turns, while record stores receive each
original turn individually in order. Benchmarks retain the existing session
boundaries, 20-turn default, and 12,000-character summary batch limit. Zeta has
no summary and uses single-turn transactions. Benchmark QA never writes back.

The hybrid locks access and snapshots logical component state before writing.
If any component fails, all component records, summaries, IDs, revisions,
evictions, and truncation flags return to their pre-transaction values. Service
objects and model weights are not copied. Logical snapshots currently include
stored embedding vectors, so transaction overhead grows with retained memory.
Rollback cannot undo provider calls: attempted-call counts, tokens, and elapsed
times are retained, including failed work. Errors propagate normally.

Benchmark facts use `TemporalFactStore` and the existing speaker/provenance
adapter. Live chat uses current-state `FactStore`; API clients cannot switch
chat to benchmark fact history. Existing fact extraction rules still apply.

## Retrieval and context packing

The packing identity is `hybrid-reserved-shares-spillover-v1`.

1. Retrieve independently, applying k to each record store before packing.
   Tag entries with `metadata.component` and a textual component label.
2. Reserve the first component's floor(total × share) tokens; give the remaining
   tokens to the second component. Pack each store's ranked whole records within
   its reservation and the total rendered budget. Labels and separators count.
3. A summary may be shortened with the existing explicit truncation marker to
   fit its reservation. This does not change the stored summary or its size cap.
   After reservations, expand the supplied summary into spare space, restoring
   the complete stored summary if it fits.
4. Reconsider omitted candidates in stable rank order, alternating components
   on equal ranks, using remaining total space. Never fetch records beyond k.
   Never split original turns or facts. Render components in architecture order.

Shares are reservations, not hard final caps. Unused space is reusable; whole
records and separators can leave some allowance unfilled. Scores from different
representations are not merged. Semantically overlapping facts and turns remain
independent evidence; there is no extra deduplication or conflict-resolution LLM.
If no candidate fits, supply empty context and report it. Stored fact status,
speaker, observation labels, and provenance are preserved.

## Inspection, metrics, evidence, and recovery

`inspect()` includes flat tagged `entries` for existing inspectors, detached
`components` snapshots, `component_usage`, and hybrid configuration. It performs
no model or embedding calls. Aggregate stored-entry counts count representations
(a fact and its source turn can both count), not unique conversation turns.

Benchmark storage growth and final storage include per-component metrics.
Retrieval diagnostics record reserved/used tokens, counts, and effective k for
each component. Inter-component separators are included in the total count, so
component-only token counts need not add to the total. Live chat records the
same context diagnostics; component write usage is available in its snapshot.

Cases report `component_evidence_recall`: original-turn coverage for vector
records, source-provenance coverage for facts, and null for summaries. The
aggregate `evidence_recall` remains null for hybrids rather than combining
different evidence meanings. Fact provenance does not establish that extraction
preserved the annotated answer. Reports display component coverage separately.

Schema v2 and protocol v3 remain readable for existing conditions. Hybrids add a
distinct packing identity and combined component prompt hash. Configuration
hashes cover shares, component limits, summary batching, and fact history.
Resume validates these identities and rebuilds both components for unfinished
conversations; no embeddings or live objects are restored from exports.

## Source and verification

[HybridMemory.py](../../src/HybridMemory.py),
[MemoryFactory.py](../../src/MemoryFactory.py),
[MemoryContext.py](../../src/MemoryContext.py), and
[Benchmark.py](../../src/Benchmark.py) implement the contracts.
[Hybrid tests](../../tests/test_hybrid_memory.py) exercise independent ingestion,
atomic failures, budget packing, settings, benchmark/chat/CLI behavior, and resume.
Tests use fake embeddings, tokenizers, and model responses, with no paid calls.
