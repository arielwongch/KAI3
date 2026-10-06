## Memory module contract

Memory modules implement the `MemoryModule` interface:

```python
class MemoryModule(ABC):
	def retrieve(self, query: str, k: int) -> list[MemoryEntry]: ...
	def write(self, entry: MemoryEntry) -> None: ...
```

`MemoryEntry.text` is the context that the agent injects into its prompt. A
module instance belongs to one conversation, so callers can keep separate
memory for separate sessions.

## Agent integration

Construct a module with `MemoryFactory`, then inject it into `run_ReAct`:

```python
from MemoryFactory import MemoryFactory
from ReAct import run_ReAct

memory = MemoryFactory.create_memory_module("sliding_window", max_items=10)
result, latency, tokens = run_ReAct(
	"What did we decide?",
	memory_module=memory,
)
```

Use summarization instead when a rolling summary is preferred:

```python
memory = MemoryFactory.create_memory_module(
	"summarization",
	summary_limit=10_000,
)
```

At the start of a run, the agent calls `retrieve(query=user_input, k=5)` and
adds the returned entry text to the system prompt. After the run, it writes
one combined user/assistant `MemoryEntry`. Internal ReAct thoughts, actions,
and observations are not persisted as long-term conversation memory.

An empty module returns no context. The summarization module makes an
additional LLM API call when an interaction is written, while the sliding
window module stores entries locally.

## Semantic modules

`MemoryFactory.create_memory_module("vector_store", embedder=None)` stores
original interactions, embedding overlapping tokenizer-sized chunks. Retrieval
ranks each interaction by its best chunk and returns it once, preserving metadata.

`MemoryFactory.create_memory_module("fact_store", embedder=None, extractor=None)`
stores current atomic user facts. The default extractor is `API.call_api`; injected
extractors take `(system_prompt, user_input)` and return `(text, latency, tokens)`.
It returns JSON `{"operations": [...]}` with `add` (`text`), `replace` (`id`,
`text`), or `remove` (`id`) operations. Existing IDs may be targeted once per
write. Invalid responses fail the whole write. Repeated facts are suppressed;
explicit corrections retain the existing fact ID. Retractions remove the fact.
Paraphrase deduplication and semantic correction decisions rely on the extractor.

Agent writes include `user_text` and `assistant_text` in metadata. Fact extraction
uses only user assertions as evidence; assistant text is context. Direct callers
without these fields must provide user-only `entry.text`. Entries marked
`completed=False` are ignored by the fact store. Returned facts have `type=fact`,
`fact_id`, `source` metadata, and `source_text` provenance.

Both modules accept an injectable embedder with `embed(list[str]) -> list[list[float]]`;
vector memory also requires `chunks(str) -> list[str]`. The default helper loads
the shared local English MiniLM model lazily. Embeddings are normalized and searched
exactly using cosine similarity; ties favor recently written/updated records.
Retrieval returns up to `k` records without a similarity cutoff. Blank queries and
empty stores return `[]`; nonpositive or noninteger `k` raises `ValueError`.
Blank writes are ignored. Writes prepare embeddings before committing state.
Returned entries are copies; callers cannot mutate stored records through them.

Conversation state is in-process only, without persistence or eviction. Embedding
weights are cached separately. The existing agent metrics exclude memory work.


## Budgeted benchmark integration (protocol v3)

Live chat continues to call `retrieve(query, k=5)`. The controlled benchmark
uses `iter_context_candidates(query, k=None)` and the shared `MemoryContext`
builder. Window/vector/fact modules accept a finite candidate k or all; the
builder packs whole candidates within a fixed-tokenizer allowance. Summary
rejects a candidate k and supplies its one rolling summary.

Factory options are module-specific: `max_stored_entries` for record modules,
`max_summary_tokens` plus an injected tokenizer for summaries, and
`fact_history_mode="versioned"` to select benchmark `TemporalFactStore`.
The normal `FactStore` remains the default for live chat. Defaults preserve
window capacity 10 and unlimited vector/fact stores. See
[the controlled-comparison specification](locomo_controlled_comparison.md)
for capacities, eviction, provenance operations, token counting, and validation.

## Inspection and diagnostics

Every built-in module exposes `inspect() -> dict` with `config` and `entries`.
Snapshots are detached and contain no embedding arrays. They do not retrieve,
embed, or invoke an LLM. Each entry contains text and metadata; vector entries
also include chunk counts. Callers coordinating writes must serialize inspection
with those writes, as the Flask session lock does.

`run_ReAct` accepts optional `diagnostics=dict` and `write_back=False` while
retaining its `(result, latency, tokens)` return tuple. Diagnostics capture the
retrieved entries, counts, status, final answer, per-stage seconds, and separate
agent/memory LLM accounting. The default still writes interactions to memory.
Benchmark ingestion uses the context-local accounting collector independently.
