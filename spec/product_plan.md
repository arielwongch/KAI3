# KAI3 Product Plan: Home, Chat, and LoCoMo Benchmark

## Status

Planning only. This document records the proposed product and implementation
sequence; application code has not been changed.

## Goal

Give KAI3 a clear entry point that lets a user choose between:

1. **Chat** — a normal chatbot with selectable memory architecture and a way to
   inspect the memory stored and retrieved for each chat.
2. **Test Benchmark** — configure and run the LoCoMo benchmark against selected
   memory architectures, then review quantitative scores, judge assessments,
   and per-question evidence in a readable report in markdown.

## Current state

- The Flask app currently serves a single chat page. Testing is a view inside
  that page, reached from its header.
- Five memory architectures are available: no memory, sliding window,
  summarization, vector store, and fact store.
- Chat sessions already have isolated in-process memory, diagnostics, a memory
  inspector, and JSON export.
- The benchmark runner already accepts LoCoMo data and supports memory-module,
  conversation, category, and question-limit selection, with progress,
  cancellation, partial results, and JSON export.
- The runner directly ingests conversation turns, currently runs QA through the
  ReAct agent with retrieval `k=5`, and does not write benchmark answers back
  into memory. The requested design replaces ReAct with direct conversational
  API calls.
- Existing benchmark scoring follows the project's implementation of the
  upstream LoCoMo category-specific evaluation behavior. The README currently
  calls out stemmed token F1, with category-specific handling for multi-answer,
  temporal, and adversarial/unanswerable cases; evidence recall is reported for
  applicable retrievers. It currently has no LLM judge.
- API calls use the configured DeepSeek endpoint/model (`deepseek-flash`).

## Proposed product experience

### 1. Home / landing page

Replace the current implicit chat-first entry with a home page that introduces
KAI3 and presents two prominent destinations: **Chat** and **Test Benchmark**.
Each workspace should have a clear way back home and retain its current
functionality. Home should briefly explain that Chat explores memory behavior
interactively and Benchmark compares memory architectures on LoCoMo.

### 2. Chat workspace

Keep current chat capabilities and make memory visibility discoverable:

- Choose one memory architecture for a new chat, including a no-memory baseline.
- Each chat uses exactly one architecture. A hybrid design, if introduced, is
  implemented and exposed as its own standalone memory module.
- Continue to show session history and selected architecture.
- Provide a clearly named Memory & Metrics inspector designed like a database
  management system: navigable memory collections or tables, a structured
  record grid with columns and metadata, record details, search and filters,
  plus a separate view of the exact context retrieved for a turn. Keep metrics
  and JSON export accessible from the same inspection workspace.
- Explain process-local memory lifetime and show when a restored browser session
  cannot reconnect to its server-side memory.

### 3. Benchmark setup and execution

Keep the current LoCoMo upload and run options. Add an explicit evaluation
configuration summary before starting, including selected modules, conversations,
categories, question limit, answering model, judge model, and scoring methods.
Show run state and progress, retain cooperative cancellation, and preserve
partial results on failures/cancellation.

Each benchmark run uses exactly one memory architecture. A hybrid architecture
is an independent module and appears as one option; the UI does not combine
multiple modules in one run. To compare architectures, users launch separate
runs and compare their reports.

### 4. Results report

Present a run overview followed by module comparisons and question-level details.
At minimum report:

- Existing LoCoMo category-aware score, preserving the current meaning and
  category rules; do not relabel it as exact match.
- Plain normalized exact match and token-level F1 as transparent complementary
  measures, with category-appropriate handling documented.
- Judge score and rubric dimensions, plus judge rationale and any uncertainty.
- Evidence recall where it is supported by the retrieval trace.
- Answering and judge latency/token usage when available, memory-operation
  usage, errors, and completed/failed question counts.
- Answer, reference, retrieved context/evidence, prediction, and score details
  for each selected question.

Clearly distinguish unavailable metrics from zero scores and report denominators
so incomplete runs cannot look like complete results. Allow exporting the full
versioned run record as JSON.

## Evaluation design

### Keep benchmark-native scores

Treat the upstream LoCoMo evaluator as the reference for reproducibility and
category-aware QA scoring. Retain the existing project score and verify its
category mapping/behavior against the pinned upstream source and dataset before
changing labels or formulas. Document any known deviations. The upstream project
code is at [snap-research/locomo task_eval/evaluation.py](https://github.com/snap-research/locomo/blob/main/task_eval/evaluation.py).

### Add interpretable lexical metrics

Report exact match and token-level F1 alongside the native score, not as
substitutes for it. Normalize consistently and state the normalization rules.
For multiple valid answers, compare against each accepted answer and use the
best appropriate match. For temporal answers, preserve the benchmark's
reference-answer interpretation. For adversarial questions, separately assess
whether the system correctly abstained; lexical metrics alone can reward the
wrong behavior.

### Add DeepSeek LLM-as-judge

Use the configured DeepSeek API for a separate judge call after each answer.
The judge should receive the question, reference answer(s), model prediction,
and relevant evidence/context, with a strict structured output. It must assess:

- **Correctness**: factual agreement with reference and evidence.
- **Completeness**: whether all requested parts are answered.
- **Support / hallucination**: whether material claims are supported, and what
  claims are unsupported.
- **Abstention**: for unanswerable/adversarial cases, whether abstention is
  appropriate and avoids invented details.

Return per-dimension ordinal scores (proposed 0–2: absent/incorrect, partial,
good), an overall decision/score, concise rationale, and a confidence or
uncertainty flag. Include reference and retrieved evidence so the judge can
separate correctness from unsupported lucky guesses. The judge must not receive
the memory-module name or other information that could bias its rating. Prompt
version, judge model identifier, and structured raw response should be recorded
for auditability. Invalid judge output or API failure is a judge error, not a
zero; it must not discard the answer or lexical metrics.

### Answer generation without a ReAct loop

For LoCoMo, retrieve the selected memory module's context for each question and
call the normal conversational/chat completion API directly with the question
and retrieved context. Do not invoke `run_ReAct`, tool selection, or iterative
reasoning/action cycles. Keep QA answers out of memory (no write-back). Record
retrieved entries and direct-answer API diagnostics for inspection. The judge
is a separate API call after the answer call.

### Calibrate with human review

Before treating judge scores as dependable, provide a review workflow for a
manually checked sample of cases. Sample across all five categories, memory
modules, score bands, and judge uncertainty, including disagreements between
the native score and judge. Record human ratings using the same rubric, compare
judge/human agreement per dimension and category, inspect false positives and
false negatives, revise the judge prompt/rubric if needed, and preserve the
calibration set and prompt version. Display the sample size and calibration
summary; mark judge results as uncalibrated until a review set is completed.
Keep human review optional for ordinary runs, while making it straightforward
to export candidate cases for annotation and import/record human labels.

## Suggested result and run data

Extend the current versioned benchmark export with:

- Immutable run configuration: dataset hash, selected data, modules and module
  parameters, answer model, judge model, prompt/rubric versions, metric versions.
- For every case: category, reference, prediction, native score, exact match,
  token F1, judge dimensions/rationale/confidence/status, evidence recall,
  trace, timing/token accounting, and errors.
- Aggregates per module, category, and overall, each with numerator/denominator
  or valid-case count; separate answer completion and judge completion counts.
- Calibration metadata and optional human labels.

Exports should avoid silently mixing results from different metric or prompt
versions. Comparison should flag configuration differences.

## Proposed implementation phases

1. **Product and evaluator decisions** — settle the open questions below; map
   LoCoMo categories from the actual dataset/source and audit current scoring.
2. **Navigation and page structure** — add a home route and distinct Chat and
   Benchmark workspaces with consistent return navigation; update frontend spec.
3. **Evaluation protocol** — define native score compatibility, exact-match/F1
   normalization, category-5 abstention evaluation, judge rubric/schema,
   calibration sampling, and versioned export fields.
4. **Backend evaluation** — replace ReAct QA generation with one normal
   conversational API call per question using retrieved memory context and no
   write-back; add lexical metrics, DeepSeek judge calls, robust parse/retry/error
   handling, progress accounting, cancellation checkpoints, and aggregates
   without losing partial outputs.
5. **Benchmark report and memory inspector UI** — add readable summaries,
   separate-run comparisons, score explanations, filters, per-question evidence
   and judge details, human calibration review/export support, and a
   database-style memory browser with structured records and searchable details.
6. **Documentation and acceptance review** — update README and frontend/API
   specs; manually inspect representative category cases and partial/error
   states before considering the work complete.

## Acceptance criteria

- A user lands on a distinct home page and can enter Chat or Test Benchmark.
- Chat supports all five memory architectures, including no memory, and inspects stored and
  retrieved memory in a database-style interface with record navigation,
  structured fields, search/filter, and turn-specific retrieval context.
- Each chat and benchmark run selects one memory architecture. Hybrid
  architectures appear as individual modules.
- LoCoMo answer generation uses a direct conversational API call with retrieved
  context; it does not run the ReAct loop or write answers into memory.
- A user can configure a LoCoMo run and see an explicit summary before launch.
- Benchmark execution uses DeepSeek for answers and judge evaluation, with
  judge calls separately accounted for and failures shown without hiding valid
  answer metrics.
- Results include existing LoCoMo-native scoring, exact match, token F1, judge
  rubric dimensions, category/module breakdowns, and per-question inspection.
- Category-specific handling, especially multi-answer, temporal, and abstention
  cases, is documented and verified against the upstream evaluator.
- Human calibration cases can be exported/reviewed, and judge calibration
  status is visible.
- Progress, cancellation, partial outputs, and JSON exports remain available.

## Open questions for planning sign-off

1. Should the landing page become the root route `/`, with Chat and Benchmark at
   distinct routes, while keeping current deep links working?
2. Should judge evaluation run for every question by default? This gives the
   clearest report but adds one DeepSeek call per answer; a sampled mode costs
   less and can be used for calibration.
3. Is the proposed judge rubric scale of 0–2 per dimension acceptable, or do you
   prefer 1–5 ratings?
4. Should calibration be an in-app human annotation flow, or is export/import
   of a review sample enough for the first version?
5. Should runs be persisted across server restarts, or remain process-local
   with JSON export as the durable record?

## Risks and constraints to resolve

- LoCoMo numeric category identifiers may not match the prose ordering commonly
  assumed; the loaded dataset and source implementation must be treated as the
  authority and the UI should show category names with IDs.
- LLM judge scores can be biased, unstable, or over-credit fluent answers.
  Evidence-conditioned judging, blind module identity, versioning, and human
  calibration are needed before using them as the only headline metric.
- Full LoCoMo runs already consume answer and memory-extraction calls; judging
  adds cost and latency. Estimate calls from the selected configuration and
  expose the total clearly before run start.
- Current sessions and benchmark job state are process-local. Durable run
  history requires a separate persistence decision.
