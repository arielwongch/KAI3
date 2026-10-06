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

The server binds to loopback (`127.0.0.1`) by default. Set `HOST` explicitly if a different bind address is needed. Only the stylesheet, workspace script, and favicon are served as public files.

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

## Controlled LoCoMo comparison (protocol v3)

The benchmark now exposes **Question Only**, **Full Context**, **Sliding Window**,
**Summarization**, **Vector Store**, and **Fact Store** as separate conditions.
Live-chat modes retain their existing behavior.

Record-based modules (window/vector/facts) expose retrieval `k` and stored-record
capacity. Summarization exposes only its summary-size limit. All four memory
conditions share a configurable context-token allowance (default 2,000). These
are fixed, pinned MiniLM tokenizer counts, not exact DeepSeek tokens. The first
memory benchmark downloads the tokenizer if it is not cached; tokenizer failure
stops preparation before paid calls. Actual provider token usage is separate.

The default `k=all` considers every retained record; finite k considers only the
first k ranked/recent records. Whole records are packed within the token allowance,
including labels and separators. Oversized candidates are skipped without going
beyond k. Sliding window selects recent turns and supplies them chronologically.
Its default capacity is 10; vector/fact capacity defaults to unlimited. Finite
capacity evicts oldest records, including old fact versions, and exports record
these evictions. Summaries use a token-size limit with explicit truncation tracking.

Full Context supplies the complete conversation and is exempt from the memory
allowance; Question Only supplies no conversation. Both use fresh requests and
retain no memory. The independent conservative whole-request context guard still
applies. The legacy `no_memory` CLI/API alias maps to Full Context by default.

```powershell
python src/Benchmark.py --dataset data/locomo/locomo10.json --output vector_results.json --modules vector_store --retrieval-k 8 --max-stored-entries 100 --memory-context-tokens 2000 --all-conversations --question-limit 0
python src/Benchmark.py --dataset data/locomo/locomo10.json --output summary_results.json --modules summarization --max-summary-tokens 2000 --memory-context-tokens 2000 --all-conversations --question-limit 0
python src/Benchmark.py --dataset data/locomo/locomo10.json --output full_results.json --modules full_context --all-conversations --question-limit 0
python src/Benchmark.py --dataset data/locomo/locomo10.json --output question_results.json --modules question_only --all-conversations --question-limit 0
```

Use `--retrieval-k all` and `--max-stored-entries unlimited` for vector/facts.
Unsupported settings are rejected rather than silently ignored. Summary accepts
neither record capacity nor retrieval k. Settings are saved per run and resume
requires the same protocol, configuration, prompts, question manifest, and tokenizer.

Benchmark facts retain searchable superseded/corrected/retracted assertions with
speaker/status/observation labels and validated dialogue provenance. Corrections
are labelled as corrections, not established historical truth. Session dates
record observation times rather than inferred real-world validity intervals.
Live-chat fact replacement/retraction remains current-state behavior.

New schema-v2 exports report **judged accuracy**, **judge completion**, and
**end-to-end success** (confirmed correct / all selected questions). Judge/answer
failures, context rejection, ingestion-blocked questions, and unattempted questions
remain visible in the denominator. Active/interrupted results are provisional.
Evidence recall for facts measures source provenance coverage, not proof that
extraction preserved all annotated detail. Reports distinguish that basis from
original-turn evidence coverage and report conditional accuracy with group counts.

Legacy schema-v1 reports stay readable and keep their saved metrics. Unambiguous
legacy full-context runs display Full Context; ambiguous inputs retain a legacy
label. Legacy runs cannot resume into v3: start a new run to avoid mixing protocols.
See [the design and acceptance criteria](spec/locomo_controlled_comparison.md).

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
jobs to compare architectures. No memory is available as a full-context, zero-storage, zero-retrieval baseline. Each QA
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
`interrupted`; they are not resumed automatically; use **Resume unfinished work** with the original dataset. Export completed results as
JSON when you need a portable copy.

The protocol directly writes one speaker-labelled, timestamped entry per dataset
turn, in numeric session order, into fresh memory for the selected
module/conversation.
Supplied image captions are included; images are not fetched. Fact extraction
uses a benchmark-only adapter that preserves speaker names and accepts assertions
from both participants. Live chat still extracts only user assertions. Questions
retrieve according to configured k and the shared context-token allowance and use the normal conversational API directly; answers are never
written back.
Ground truth and evidence labels are used only after prediction.

QA scores reproduce the category-specific deterministic rules in the
[upstream evaluator](https://github.com/snap-research/locomo/blob/main/task_eval/evaluation.py):
stemmed token F1, multi-answer F1 for category 1, first semicolon-delimited answer
for category 3, and the upstream abstention phrase check for category 5. The
report also includes normalized exact match, token F1, and a DeepSeek judge score
for correctness, completeness, support, and abstention. Judge failures do not
discard answer metrics. Incomplete/failed predictions are excluded from means
and shown separately. Evidence recall is available for window/vector/full context with dialogue IDs and
nonempty evidence; summary coverage is null and facts use source provenance. DeepSeek supplies the binary semantic correctness judgment.

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

Install `requirements-test.txt` and Node.js 22+ to run the complete unittest
suite. DOM-free JavaScript tests cover history migration, restart blocking,
safe text rendering, inspector views, and saved-run resume/upload behavior.
They use Node's built-in test runner with no npm dependencies or browser needed.
A missing Node runtime fails the frontend tests instead of silently skipping them.
GitHub Actions installs Python 3.12 and Node.js 22 and runs the full suite with
dummy credentials and offline model settings.

### Binary evaluation with no memory

Run all 10 bundled conversations and all questions in PowerShell:

```powershell
py src/Benchmark.py --dataset data/locomo/locomo10.json --output no_memory_results.json --modules no_memory --all-conversations --question-limit 0
```

Configure `DEEPSEEK_API_KEY` as described above. In Test Benchmark, select **No memory**, **All conversations**, all categories, and question limit **0**.

In benchmarks, **No memory** defaults to a full-context, no-persistent-memory baseline. Each question gets the complete conversation in a new request, with sessions in numeric order and dates, speakers, dialogue IDs, and supplied captions. No chat history, summaries, retrieved passages, or previous answers are reused. The live chat No memory mode still retains nothing.

For the question-only baseline, add `--no-memory-context question_only` or select **Question only** in the benchmark form. Exports distinguish these protocols and record the input mode.

Before each answer call, the runner checks a conservative UTF-8 byte-based token budget plus framing allowance and output reserve. This is not an exact DeepSeek tokenizer count and can reject inputs that would fit. The defaults are a 1,000,000-token context limit and 8,192 output tokens, configurable using `--context-limit` and `--max-output-tokens`. Over-budget requests receive `context_limit_exceeded` without an API call, truncation, summarization, or retrieval. Results include `context_limit_count` separately from incorrect answers.

Answer calls use fixed `deepseek-flash`, thinking enabled, high reasoning effort, and the recorded output limit. Temperature is omitted because thinking mode does not support it. Automatic SDK retries are disabled; the runner applies up to five attempts for transient errors with bounded backoff. Timeout/connection retries can repeat a provider request whose response was lost. Exports save raw answer responses (including API IDs and usage), latency, finish reason, actual prompt tokens when returned, prompt version, and request settings. Length-limited answers remain unscored.

DeepSeek compares each prediction with the ground truth using binary semantic correctness (`correct`: 1 or 0), accepting equivalent wording and date formats. Category 5 is judged as unanswerable. Ground truth is supplied only to the judge. Exports report `accuracy = correct_count / scored_count` per category and overall (weighted by questions). Failed predictions or judge calls remain unscored, with counts reported separately; they are never silently treated as incorrect. Existing F1 and 0?2 diagnostic rubric fields remain available.

### External-memory comparison

Run each strategy separately with identical question selection, prompt, answer model, and decoding settings:

```powershell
py src/Benchmark.py --dataset data/locomo/locomo10.json --output facts_results.json --modules fact_store --all-conversations --question-limit 0
py src/Benchmark.py --dataset data/locomo/locomo10.json --output retrieval_results.json --modules vector_store --all-conversations --question-limit 0
```

Every conversation creates an empty, isolated memory instance. Ingestion preserves labelled, timestamped turns in numeric session order. Summarization updates its rolling summary in batches of up to 20 turns and 12,000 characters, without crossing session boundaries; a single oversized turn is kept intact. Other memory architectures write one turn at a time. This reduces the bundled dataset's summary requests from 5,882 to 399 before answering and judging. The question limit only limits QA, so the selected conversations must still be ingested in full. Questions retrieve whole entries within the configured k and token allowance, use the same answer prompt/settings as the full-context baseline, and never write questions or predictions back. `vector_store` is the original-turn retrieval baseline; `fact_store` and `summarization` transform dialogue into memory representations. Summary/fact extraction model settings and summary batch limits are recorded separately. Batching changes the summary construction protocol and can affect scores. Resuming an older saved run preserves its per-turn ingestion; start a new run to use batching.

Exports include retrieved items with ranks and cosine scores for vector/fact search, ingestion/write latency, session-by-session logical storage growth, final storage size, retrieval/answer latency, API usage, and evidence recall where original dialogue IDs are available. Summary/fact provenance is not treated as proof that an annotated fact survives transformation; evidence recall remains unavailable for those representations. New memory-context counts use the pinned benchmark tokenizer; legacy retrieved budgets are UTF-8 byte proxies. Storage sizes describe text and JSON snapshots, excluding embedding arrays and Python overhead. Monetary costs remain `null` when pricing is unavailable. The `efficiency` report aggregates retrieval budgets, latency, and evidence recall.

### Long benchmark runs and recovery

HTTP 402 means insufficient DeepSeek account balance, not an invalid API key. Top up the account, then use **Resume unfinished work**. HTTP 401 requires correcting the key and restarting the server before resuming. The runner stops on permanent provider errors (400/401/402/403/422) instead of failing all later questions. Transient rate-limit/server/connection/timeout failures receive at most five attempts, a 180-second request timeout, and exponential delays capped at 60 seconds, respecting numeric Retry-After. Retry waits can be cancelled. Exhausted transient failures are saved and the run continues; resume retries those cases.

Every question is checkpointed. CLI runs also checkpoint their output file while running. Resume from a saved export:

```powershell
py src/Benchmark.py --dataset data/locomo/locomo10.json --output recovered_results.json --resume results.json
```

Resume validates the dataset hash and model/prompt compatibility, keeps fully scored cases (including incorrect answers), and reuses saved predictions when only judging failed. Failed cases are replaced rather than appended. For compatible v3 resumes, external-memory stores are rebuilt for unfinished conversations; summary/fact ingestion may incur additional calls and generate different memories. Prior ingestion snapshots are retained for auditing. Full-context/question-only baselines need no memory rebuild. Frontend resume uses the original dataset saved on the server, including after a restart. If that dataset is unavailable, the report requests an upload and validates it against the saved run. API keys remain server-side and are read from `src/.env` (environment variables take precedence).

### Import saved benchmark reports

On **Test Benchmark**, choose **Import results JSON** in the top bar and select a previously exported results file. The browser restores score tables, question details, retrieved evidence, memory snapshots, and timing fields locally without API calls. Older exports display their saved judge rubric; absent binary accuracy or newer metrics remain unavailable. Dataset files and malformed exports receive a clear validation message.

Imported reports are read-only: resume and human-label uploads are disabled. **Export JSON** downloads the original imported data locally. Choose **New run** to return to normal benchmarking. To view an imported report after refreshing the page, select the file again. The source file and server runs are unchanged.

### Live progress, memory review, and background workers

The benchmark sidebar shows **New benchmark** and **Saved runs**. Open a saved run to follow its current progress or export it; interrupted, cancelled, and failed runs can be resumed. Imported exports keep the results layout and display a **Read-only ? Imported report** badge.

Progress counts ingestion turns and question stages separately, reports answered/judged counts, and shows the current conversation and operation. **Review memory before answering** pauses after each conversation is ingested, before its question calls. **Inspect memory** opens the actual store snapshot; for full-context runs it opens the supplied conversation. **Continue evaluation** releases that review pause. Memory extraction may already have used the API. Cancelling also works while reviewing.

**Run in background** is enabled by default in the benchmark form. It launches an independent hidden Python process using the current interpreter and credentials. The run continues if you close the browser or stop the web server terminal. Start the server again and return to **Test Benchmark ? Saved runs** to reconnect. The computer must remain awake; shutdown/reboot terminates workers. Lost workers are marked interrupted and require explicit resume. A global worker lease prevents concurrent background evaluations. Waiting for memory review also keeps the worker alive until continued or cancelled.

Snapshots, the original dataset, control files, and worker logs are stored in the server's `instance/benchmark_runs/` directory. No API key is stored in those files. The original dataset allows resuming after a restart without reuploading it. For older saved runs without a saved dataset, click Resume and use the requested original-dataset upload. Uncheck **Run in background** to use the existing server-thread execution. CLI behavior is unchanged; interactive review is available through the web UI.

The benchmark top bar also has **View saved results**, which lists JSON files under `data/result/`, including nested folders. Add more reports or folders there, then press the refresh button beside the dropdown. Selecting a file opens the same read-only report view; no model calls are made.
