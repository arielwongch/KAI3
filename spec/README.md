# Component and feature specifications

This directory describes implemented behavior, organized by ownership. Last
source review: 2026-10-08. Check dates are not implementation/release dates.
The shared shell, Compare Runs, benchmark export/result-library integration, local
setup, and recovery documentation were reconciled on 2026-11-02. This focused
update does not change the review date of unaffected memory/protocol components.
The earlier workspace/result-library update is committed and pushed on `main` as `8035e9b`; current
verification at that milestone included the 143-test offline suite and scoped desktop/phone browser
checks. The post-commit Markdown review changed documentation only. Subsequent
periodic-memory, reranking, and scatter-plot changes were committed in `6679238`.
The 2026-11-03 audit adds offline adjudication and focused policy regressions;
human calibration and effectiveness confirmation remain pending. The current
offline suite passed 179 tests. See [updates](../UPDATES.md).
[Development plans](../plans/README.md) separately track sequences, historical
dates, remaining acceptance work, and unscheduled proposals.
See [updates](../UPDATES.md), [progress](../PROGRESS.md), and the
[complete documentation review](../plans/documentation_review.md) for scope.

## Local development

| Feature | Scope |
| --- | --- |
| [Local setup and startup](local_setup.md) | Python 3.12, shell-specific setup, environment checks, startup messages, local runtime files |

## Memory components

| Component | Scope |
| --- | --- |
| [Shared interface](memory/interface.md) | Entries, factory, agent integration, snapshots, shared lifecycle |
| [Sliding window](memory/sliding_window.md) | Recent-turn storage, eviction, chronological context |
| [Rolling summary](memory/summarization.md) | Summary updates, batching input, size enforcement |
| [Vector memory](memory/vector_store.md) | Chunk embeddings, original-turn retrieval, similarity ordering |
| [Vector Store + Reranker](memory/vector_store_reranker.md) | Vector shortlist, pinned cross-encoder, whole-turn reranking |
| [Current facts](memory/fact_store.md) | Live-chat assertions, replacement, removal, current-fact retrieval |
| [Temporal facts](memory/temporal_fact_store.md) | Benchmark versions, provenance, updates, historical retrieval |
| [Recent-window hybrids](memory/window_hybrid.md) | Alpha/Beta/Gamma recent windows, long-term writes, and context packing |
| [Periodic window modes](memory/periodic_window.md) | Recent k entries with summary/fact updates every k writes and a pre-QA flush |
| [No memory](memory/no_memory.md) | No-op storage/retrieval component |

## Benchmark features

| Feature | Scope |
| --- | --- |
| [Lifecycle and configuration](benchmark/lifecycle.md) | Conditions, defaults, ingestion, isolation, QA, no write-back |
| [Reference baselines](benchmark/baselines.md) | Question-only, full context, exemptions and aliases |
| [Context budget](benchmark/context_budget.md) | Tokenizer, candidate k, whole-record packing, request guard |
| [Evaluation](benchmark/evaluation.md) | Lexical/judge scores, failures/denominators, evidence, human review |
| [Offline adjudication](benchmark/adjudication.md) | Blinded packets, private keys, human labels, calibration denominators and schema |
| [Results and resume](benchmark/results_and_resume.md) | Exports, comparison copies, diagnostics, persistence, imports, recovery, compatibility, confirmed run deletion |

The [hybrid memory specification](memory/hybrid.md) covers delta (summary + vector),
epsilon (summary + facts), and zeta (vector + facts), including independent
ingestion, configurable context shares, atomic writes, and component diagnostics.

## Frontend features

| Feature | Scope |
| --- | --- |
| [Shared workspace shell](frontend/workspace_shell.md) | Common sidebar, typography, headers, collapse/mobile drawer, focus and asset ownership |
| [Chat](frontend/chat.md) | Home/navigation, sessions, composer, messages, chat API |
| [Benchmark workspace](frontend/benchmark.md) | Setup, progress/review, reports, saved/imported results, confirmed run deletion, named export to Compare, API |
| [Compare Runs](frontend/compare_runs.md) | JSON library/enrichment, duplicates, rename/delete, separate downloads, configurable scatter plot, sorted table, tooltips, coverage and folder boundary |
| [Memory inspector](frontend/memory_inspector.md) | Stored records, turn context, metrics, snapshot export |

## Documentation ownership

Each component/feature explains purpose, interfaces/configuration, stored data,
write or interaction flow, retrieval/read behavior, failures/limitations, and
source/test evidence as applicable. Shared behavior has one canonical home:
module interfaces here, packing under benchmark, scoring under evaluation,
and visual interactions under frontend. Link across those boundaries rather than
duplicating rules. Existing tests listed in specs are coverage references, not
claims that a new test or experiment was run during documentation review.

The old top-level spec filenames are navigation pointers for existing links and
open editor tabs. Development plans moved out of this directory; archived
proposals under `plans/archive/` retain their historical wording with a notice.
