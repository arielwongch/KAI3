# Recent-window hybrid memory

Alpha, Beta, and Gamma combine a finite recent window with one long-term store.
They are available through the factory, chat, benchmark API/CLI, and UI alongside
Delta, Epsilon, Zeta, and Vector Store + Reranker.

| Mode | Long-term store | Write policy |
| --- | --- | --- |
| Alpha | Rolling summary | Summarize only turns evicted from the recent window |
| Beta | Vector store | Embed only turns evicted from the recent window |
| Gamma | Fact store | Extract from every incoming turn, including retained recent turns |

Implementation: [WindowHybridMemory.py](../../src/WindowHybridMemory.py).
The public Alpha/Beta/Gamma classes are also exported from HybridMemory.py.

## Configuration and writes

Factory `max_items` controls the recent window and defaults to 10. Alpha accepts
`summary_limit` or `max_summary_tokens` with a tokenizer. Beta/Gamma accept
`max_stored_entries` for their long-term tier and an embedder; Gamma additionally
accepts an extractor and `fact_history_mode`. Benchmark Gamma uses versioned facts;
live chat uses current facts. Options belonging to other architectures are rejected.

Chat `/get` accepts top-level `window_size`, a positive integer fixed for the
conversation. It defaults to 10. Benchmark Alpha/Beta/Gamma use `window_size`
(default 100), exposed as `--window-size` in the CLI. Standalone sliding-window
benchmarks keep main's default capacity of 10 and accept the same alias. A
conflicting explicit `max_stored_entries` is rejected for standalone windows.

Writes stage a detached pending window before modifying long-term state. Child
writes commit atomically; if extraction, summarization, or embedding fails, both
tiers retain their previous state. Alpha supports session-bounded benchmark
batches, retaining individual recent turns while summarizing the evicted prefix
once per batch. Beta/Gamma ingest one turn at a time. Inspection and retrieval
share a lock with writes, and snapshots remain detached without model calls.

## Retrieval and context

Live chat returns up to five recalled long-term records (one summary for Alpha)
plus the entire recent window, oldest to newest. Explicit recent corrections take
precedence in the rendered prompt. Standalone sliding-window chat also supplies
its full window. Low-level retrieve still accepts its own k.

Benchmarks use the existing pinned tokenizer and context allowance. Retrieval k
applies only to long-term candidates (null means all); the retained recent turns
are also eligible. Candidate order is long-term retrieval order followed by the
chronological recent window. Packing greedily includes whole records in that
order, counting section headings and separators. Oversized candidates are omitted
and reported in packing diagnostics; fitting all recent turns is not guaranteed.
Questions and predictions are never written back. Beta evidence recall covers
original dialogue IDs across both tiers; Alpha/Gamma combined recall is unavailable.

Snapshots tag records with `memory_tier` and `memory_component` and include the
long-term configuration. Reports persist window settings, write/batch policy,
context diagnostics, provenance, and usage. Resume retains v3 compatibility
checks, including the normalized configuration hash and memory prompt identity;
pre-v3 test2 reports can be imported but require a new run to use this protocol.

## Verification

`test_window_hybrid_memory.py` checks partitioning, correction/retraction,
transactional failures, locking, detached inspection, labels, and token packing.
`test_hybrid_integration.py` checks chat settings, benchmark ingestion/accounting,
CLI, cancellation, background exports, and resume. Node frontend regressions
cover validation, persistence, request settings, locking, and both hybrid families.


As of 2026-11-02, Beta/Gamma embedded long-term retrieval uses the shared
[reranking policy](vector_store_reranker.md), with configurable `candidate_k`
(default 50). Their write policies remain unchanged. The separate
[periodic window modes](periodic_window.md) process the latest k incoming entries
every k writes and flush the final partial batch before benchmark QA.
