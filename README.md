# KAI3

```bash
cp src/.env.example src/.env
```

## Agent memory modes

Create one memory module per conversation and pass it to the ReAct agent:

```python
from MemoryFactory import MemoryFactory
from ReAct import run_ReAct

memory = MemoryFactory.create_memory_module("sliding_window", max_items=10)
result, latency, tokens = run_ReAct(
	"Remember that the deployment is on Friday.",
	memory_module=memory,
)
```

For a rolling summary instead:

```python
memory = MemoryFactory.create_memory_module(
	"summarization",
	summary_limit=10_000,
)
```

The agent retrieves context before each run and stores the completed
user/assistant interaction afterward. Existing callers may still pass
`memory=["..."]`; this legacy path is used when `memory_module` is omitted.

