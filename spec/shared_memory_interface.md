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
