# Component and feature specifications

This directory describes implemented behavior, organized by ownership. Last
source review: 2026-10-08. Check dates are not implementation/release dates.
[Development plans](../plans/README.md) separately track sequences, historical
dates, remaining acceptance work, and unscheduled proposals.

## Memory components

| Component | Scope |
| --- | --- |
| [Shared interface](memory/interface.md) | Entries, factory, agent integration, snapshots, shared lifecycle |
| [Sliding window](memory/sliding_window.md) | Recent-turn storage, eviction, chronological context |
| [Rolling summary](memory/summarization.md) | Summary updates, batching input, size enforcement |
| [Vector memory](memory/vector_store.md) | Chunk embeddings, original-turn retrieval, similarity ordering |
| [Current facts](memory/fact_store.md) | Live-chat assertions, replacement, removal, current-fact retrieval |
| [Temporal facts](memory/temporal_fact_store.md) | Benchmark versions, provenance, updates, historical retrieval |
| [No memory](memory/no_memory.md) | No-op storage/retrieval component |

## Benchmark features

| Feature | Scope |
| --- | --- |
| [Lifecycle and configuration](benchmark/lifecycle.md) | Six conditions, defaults, ingestion, isolation, QA, no write-back |
| [Reference baselines](benchmark/baselines.md) | Question-only, full context, exemptions and aliases |
| [Context budget](benchmark/context_budget.md) | Tokenizer, candidate k, whole-record packing, request guard |
| [Evaluation](benchmark/evaluation.md) | Lexical/judge scores, failures/denominators, evidence, human review |
| [Results and resume](benchmark/results_and_resume.md) | Exports, diagnostics, persistence, imports, recovery, compatibility |

## Frontend features

| Feature | Scope |
| --- | --- |
| [Chat](frontend/chat.md) | Home/navigation, sessions, composer, messages, chat API |
| [Benchmark workspace](frontend/benchmark.md) | Setup, progress/review, reports, saved/imported results, API |
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
