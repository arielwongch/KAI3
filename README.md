# KAI3

```bash
cp src/.env.example src/.env
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python src/app.py
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
user/assistant interaction afterward.

For semantic retrieval of past interactions or current user-stated facts:

```python
memory = MemoryFactory.create_memory_module("vector_store")
memory = MemoryFactory.create_memory_module("fact_store")
```

All four modes are available in the chat UI. Each chat keeps its selected mode
and isolated memory for the lifetime of the server process. Restarting the server
clears memory; browser history does not restore it.

The semantic modes use `sentence-transformers/all-MiniLM-L6-v2` on CPU for
English-first retrieval. First use downloads the model into the Hugging Face
cache; subsequent runs reuse cached weights. The model is loaded lazily and shared
across chats. Vector memory indexes overlapping chunks but returns whole original
interactions. Fact memory uses the existing DeepSeek credentials to extract and
update current user-stated facts, then searches them using the same embeddings.
No database is required. Neither store evicts records automatically.

Use Python 3.12 for the local ML dependencies. Tests mock both embeddings and
model API responses and do not require credentials or a model download:

```bash
python -m unittest discover -s tests -v
```

An optional real-model smoke test downloads the embedding weights on first use
and checks paraphrases, long interactions, and fact retrieval without LLM calls:

```bash
python tests/smoke_semantic_memory.py
```

Existing response latency and token counts describe the agent calls, not all
embedding and fact-extraction work. Memory write failures return the existing
HTTP 503 response; previous stored memory is preserved.
