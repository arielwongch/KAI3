# Shared memory interface

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

## Purpose and ownership

One memory instance represents one chat or one benchmark conversation. Modules
transform entries into their own representation and return text for prompts.
Module-specific algorithms live in the component specifications linked from the
[specification index](../README.md). Benchmark ingestion and QA are defined in
[lifecycle](../benchmark/lifecycle.md); its token allowance is defined in
[context budget](../benchmark/context_budget.md).

## Interfaces

```python
@dataclass
class MemoryEntry:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

class MemoryModule(ABC):
    def write(self, entry: MemoryEntry) -> None: ...
    def retrieve(self, query: str, k: int) -> list[MemoryEntry]: ...
    def iter_context_candidates(self, query: str, k: int | None = None): ...
    def inspect(self) -> dict: ...
```

`write` and `retrieve` are abstract requirements. The base inspection and
candidate methods raise `NotImplementedError`; all built-in modules implement
them. Candidate implementations may return lists or iterators; callers consume
them as iterables. Benchmark candidates and inspection snapshots are detached.
Live retrieval copy behavior is module-specific; window retrieval exposes its
stored entries. `MemoryEntry.text` is the text supplied to the prompt; metadata
holds provenance, type labels, and diagnostics rather than automatically rendered
context. Temporal facts explicitly render selected metadata into their text.

## Construction and configuration

```python
from MemoryFactory import MemoryFactory
from ReAct import run_ReAct

memory = MemoryFactory.create_memory_module("sliding_window", max_stored_entries=10)
result, latency, tokens = run_ReAct("What did we decide?", memory_module=memory)
```

Factory options are module-specific. Window supports `max_items` and
`max_stored_entries`; summary supports `summary_limit`, `max_summary_tokens`,
and an injected tokenizer; vector/facts support `max_stored_entries` and an
injected embedder. Facts also support an extractor and `fact_history_mode`.
The default fact mode is `current`; benchmark v3 requires `versioned`.

The application and benchmark construct `NoMemory()` directly for their no-memory
paths. Importing `NoMemory` also installs support for `no_memory` on the factory;
do not assume that alias exists before that import. The factory rejects known
capacity/summary/history controls used with the wrong architecture. The benchmark
performs stricter capability-based validation before constructing modules.

## Stored data and lifecycle

Memory representations are process-local; modules do not reload persisted
conversation state. Embedding models are loaded lazily and shared; cached weights
are independent of stored records. [Saved benchmark results](../benchmark/results_and_resume.md)
contain logical snapshots, not live module instances or embedding arrays.

Each module defines its capacity and eviction rules. Window is finite; vector
and facts default to unlimited but accept finite capacities. Summary holds one
string. NoMemory retains no entries.

## Agent write and retrieval flow

At the start of `run_ReAct`, the agent calls `retrieve(user_input, k=5)` and joins
entry texts into its system prompt. After the interaction it normally writes one
combined user/assistant entry. Metadata includes `user_text`, `assistant_text`,
and completion information. Internal thoughts/actions/observations are not stored
as long-term conversation memory. The current fact store treats only user text
as assertion evidence; callers without `user_text` must pass user-only entry text.

`run_ReAct` accepts `write_back=False` and optional `diagnostics=dict`, preserving
its `(result, latency, tokens)` return tuple. Benchmark QA uses its own direct
answer path and never writes questions or predictions back.

## Inspection, diagnostics, and failures

`inspect()` returns `{"config": ..., "entries": [...]}` with detached text and
metadata. It does not retrieve, embed, or call an LLM. Vector entries additionally
report chunk counts. Flask serializes operations with a per-session lock;
direct callers must coordinate inspection/writes where the module does not do so.

Diagnostics distinguish retrieval, agent, and write timings, retrieved entries,
completion status, and agent/memory LLM accounting. The tuple's latency/token
values describe agent work rather than all memory work. Inspection display is
specified in [memory inspector](../frontend/memory_inspector.md).

Empty-memory behavior and validation depend on the component. There is no shared
fallback that hides extraction, embedding, or retrieval errors. Component specs
define transactional guarantees and the benchmark records stage failures.

## Source and verification

[MemoryModule.py](../../src/MemoryModule.py), [MemoryEntry.py](../../src/MemoryEntry.py),
[MemoryFactory.py](../../src/MemoryFactory.py), [ReAct.py](../../src/ReAct.py), and
[Diagnostics.py](../../src/Diagnostics.py) implement this contract.
[Memory integration tests](../../tests/test_memory_integration.py) and
[diagnostics tests](../../tests/test_diagnostics_benchmark.py) cover integration.
