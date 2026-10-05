# KAI3

## Local setup

Install Python 3.12 first, then run the commands below from the project folder.
Choose the instructions for your terminal.

### macOS / Linux (Bash or Zsh)

```bash
cp src/.env.example src/.env
python3.12 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python src/app.py
```

### Windows (PowerShell)

```powershell
Copy-Item src/.env.example src/.env
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe src/app.py
```

The Windows commands use the virtual environment's Python directly, so activation
and PowerShell execution-policy changes are unnecessary. If `py -3.12` cannot
find Python, install Python 3.12 and reopen your terminal.

Edit `src/.env` and replace `YOUR_API_KEY` with your DeepSeek API key before using
the chat. Copy the example file only during initial setup; copying it again
overwrites your saved configuration.

Open http://localhost:5000 after starting the app. The home page links to Chat
and Test Benchmark. Press **Ctrl+C** to stop it.
On subsequent runs, macOS/Linux users activate the environment and run
`python src/app.py`; Windows users run `.\venv\Scripts\python.exe src/app.py`.
Install dependencies again when `requirements.txt` changes.

If port 5000 is occupied (for example by macOS Control Center/AirPlay), choose
another port:

macOS / Linux, with the virtual environment activated:

```bash
PORT=5001 python src/app.py
```

Windows PowerShell:

```powershell
$env:PORT = "5001"
.\venv\Scripts\python.exe src/app.py
```

Then open http://localhost:5001. The default remains port 5000.

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

All five modes are available in the chat UI, including **No memory** for a
baseline that stores and retrieves nothing. Each chat keeps its selected mode
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

## Session inspector and LoCoMo QA testing

Use **Memory database** in the chat header to browse stored records in a
database-style table, search record text and metadata, inspect a selected
record, view a turn's exact retrieved context, or inspect timing and token
metrics.
Snapshots do not perform searches, model calls, or embedding work. Vector memory
shows chunk counts rather than embedding arrays; fact memory shows provenance.
**Export JSON** downloads a versioned snapshot with diagnostics.

The browser now retains multiple chats and supports switching between them.
Existing single-chat history is migrated automatically. Server memory and turn
metrics remain process-local: after a restart, browser messages remain visible,
but their sessions cannot continue. Start a new chat instead. Exports are the
supported way to retain diagnostics across restarts.

Timing fields use seconds: `retrieval_seconds`, `agent_seconds` (summed agent API
call durations), `write_seconds`, and `total_seconds` (whole turn). Agent tokens
and memory LLM tokens/call counts are separate. Summary and fact extraction count
as memory LLM work. `null` token usage means unavailable, including failed calls;
embeddings have no API token count. Failed turns retain partial diagnostics.
Stored counts describe the module's logical entries, not embedding chunks.

Session endpoints:

- `GET /api/chats/<chat_id>/diagnostics` returns contents, turns, and totals.
- `GET /api/chats/<chat_id>/export` downloads the same versioned JSON.
- `POST /get` retains its existing response fields and adds `turn_id`. Restored
  clients send `requires_existing: true` to reject silent memory recreation.

Open **Test Benchmark** to use the bundled dataset under `data/` or upload
another LoCoMo JSON dataset, select one memory architecture, conversation IDs
and categories, and launch a run. The default is sliding window, the first
conversation, all categories, and ten questions per conversation. Run separate
jobs to compare architectures. No memory is available as a zero-storage,
zero-retrieval baseline. Each QA
answer uses one direct conversational API call with retrieved context; it does
not use the ReAct loop or write answers back into memory. A separate DeepSeek
judge call evaluates every answer.
A question limit of zero evaluates every matching question. API calls during
benchmark execution use the configured DeepSeek credentials. Only one frontend
benchmark runs at a time; cancellation takes effect between operations.

The same runner is available from the terminal:

```bash
python src/Benchmark.py --dataset /path/to/locomo10.json \
  --output /path/to/results.json --modules sliding_window \
  --sample-ids conv-26 --categories 1 2 3 4 5 --question-limit 10
```

Use actual `sample_id` values from your dataset. Omit `--sample-ids` to use the
first conversation. Use `--all-conversations --question-limit 0` for the full
dataset, or select **All conversations** and set the question limit to zero in
the frontend. The CLI writes partial results if interrupted.

Frontend benchmark snapshots are saved under `src/instance/benchmark_runs/`.
Completed runs remain available after a server restart. Runs interrupted by a
restart are restored with their last saved partial results and marked
`interrupted`; they are not resumed automatically. Export completed results as
JSON when you need a portable copy.

The protocol directly writes one speaker-labelled, timestamped entry per dataset
turn, in numeric session order, into fresh memory for the selected
module/conversation.
Supplied image captions are included; images are not fetched. Fact extraction
uses a benchmark-only adapter that preserves speaker names and accepts assertions
from both participants. Live chat still extracts only user assertions. Questions
retrieve `k=5` and use the normal conversational API directly; answers are never
written back.
Ground truth and evidence labels are used only after prediction.

QA scores reproduce the category-specific deterministic rules in the
[upstream evaluator](https://github.com/snap-research/locomo/blob/main/task_eval/evaluation.py):
stemmed token F1, multi-answer F1 for category 1, first semicolon-delimited answer
for category 3, and the upstream abstention phrase check for category 5. The
report also includes normalized exact match, token F1, and a DeepSeek judge score
for correctness, completeness, support, and abstention. Judge failures do not
discard answer metrics. Incomplete/failed predictions are excluded from means
and shown separately. Evidence recall is available only
for window/vector retrieval with dialogue IDs and nonempty evidence; it is `null`
for summary/fact retrieval. No LLM judge is used.

Exports include dataset SHA-256 (canonicalized parsed JSON), protocol, answer and
judge model identifiers, judge prompt version, module configuration, ingestion
metrics, final memories, question traces, predictions, scores, and failures.
Fixed model names do not imply
provider-version pinning; record exports when comparing runs.

Benchmark endpoints:

- `POST /api/benchmarks`: `{ "dataset": [...], "options": { "module": "sliding_window",
  "sample_ids": [...], "categories": [...], "question_limit": 10 } }`; returns
  `run_id` with HTTP 202.
- `GET /api/benchmarks/<run_id>`: progress and partial results.
- `POST /api/benchmarks/<run_id>/cancel`: requests cooperative cancellation.
- `GET /api/benchmarks/<run_id>/export`: downloads results JSON.
- `GET /api/benchmarks/<run_id>/review`: downloads cases for manual 0–2 rubric ratings.
- `POST /api/benchmarks/<run_id>/review`: imports human ratings and reports judge/human exact agreement.

Tests use mocked models and embeddings and require no paid calls. The new scoring
dependency, NLTK, uses its bundled Porter stemmer; no corpus downloads are needed.

For the optional DOM-free JavaScript state tests (history migration, restart
blocking, safe text rendering, and error refresh), install `requirements-test.txt`
and run the same unittest command. These tests use QuickJS; no browser or Node.js
installation is required.
