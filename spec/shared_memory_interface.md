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

At the start of a run, the agent calls `retrieve(query=user_input, k=5)`, except
standalone Sliding Window uses its configured capacity for `k`. It adds the
returned entries to the system prompt. After the run, it writes
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

## Hybrid modules

Factory identifiers `alpha`, `beta`, and `gamma` construct `Alpha`, `Beta`, and
`Gamma` from `HybridMemory.py`. All accept `max_items=10`. Alpha additionally
accepts `summary_limit=10_000`; Beta accepts `embedder`; Gamma accepts `embedder`
and `extractor`, with the same contracts as their standalone components.

- Alpha summarizes only entries evicted from its window.
- Beta archives and embeds only evicted entries, preserving original interactions.
- Gamma updates current facts on every write; recent dialogue and facts can overlap.

`retrieve(query, k)` requires a positive integer `k`, excluding booleans, and
returns long-term context followed by the full chronological window. Alpha
returns zero or one summary; Beta/Gamma retrieve up to `k` semantic records.
Blank semantic queries still return recent entries. Blank writes are ignored.
Incomplete entries retain the existing component semantics: recent dialogue is
stored, but Gamma does not extract facts from `completed=False` entries.

Hybrid writes stage a copied window, update the long-term component, and only
then commit the window. Model, extraction, or embedding failures preserve both
tiers. Reads, writes, and inspection share a lock. Entries and snapshots are
detached copies. Metadata adds `memory_tier` (`recent` or `long_term`) and
`memory_component` while retaining provenance and retrieval scores.

`Alpha.write_batch(list[MemoryEntry])` stages a whole batch, summarizes its
evicted prefix once, and keeps each recent entry separate. A failed batch commits
nothing. Benchmark ingestion uses existing session-bounded input batches of up
to 20 turns and 12,000 characters (a single oversized turn remains intact).
Chat uses single-entry writes. No final-window flush occurs before benchmark QA.

Shared prompt formatting labels summary, archived turns, current facts, and recent
dialogue, and states that explicit recent corrections supersede older statements.
Diagnostics preserve original texts; prompt labels are not written into memory.

`window_size` is optional in chat requests and benchmark options; the CLI exposes
`--window-size`. It must be a positive integer and applies only to Sliding Window
and hybrids. Chat defaults to 10 combined interactions; benchmarks default to
100 speaker turns. Chat configuration becomes immutable with session creation:
an omitted setting reuses it, an explicit change returns 409, and an invalid
setting returns 400. Browser history, exports, and benchmark resume preserve it.
Older records lacking a window setting use the historical surface default.

Reports add effective `window_size`, `retrieval_policy`, hybrid context version,
and Alpha batch settings without changing export schema version 1. Beta evidence
recall uses dialogue IDs from both tiers; Alpha/Gamma evidence recall remains
unavailable. Memory call accounting continues through the existing collector.


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
