# Memory inspector and diagnostics

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

## Purpose and interfaces

Memory database provides a full-height browsing workspace for chat memory,
benchmark ingestion snapshots, and the retrieved context of individual turns.
It reads the module [inspection contract](../memory/interface.md) without invoking
retrieval, embeddings, or LLM generation.

For chat, `GET /api/chats/<chat_id>`, `/diagnostics`, and `/export` share a detached
snapshot with `schema_version=1`, chat ID, selected memory mode, model, retrieval k,
maximum iterations, `memory`, `turns`, and aggregate `totals`. Export adds download
headers; missing server memory returns 404. Flask locks the session while copying.

## Stored view state and read flow

The client tracks inspection source, selected record, view tab, and selected turn.
Chat selection/refresh fetches server diagnostics, including after failed turns.
Benchmark inspection uses the selected conversation's saved `memories` entry and
matching case diagnostics. Pending ingestion review can display its snapshot or
full transcript before any QA turn exists. Imported-result inspection stays local.

| View | Contents |
| --- | --- |
| Stored records | Searchable text/metadata table, record count, selected-record detail |
| Retrieved context | Selected turn's exact retrieved entries and available query/status details |
| Metrics | Per-turn stage timings, counts, tokens, and aggregate/ingestion diagnostics |

Record data uses text nodes rather than untrusted HTML. Record selection supports
clicks and Enter/Space. Vector snapshots expose chunk counts rather than arrays;
fact metadata exposes provenance and, for temporal facts, status/version links.
Export downloads the appropriate chat or benchmark JSON; imported snapshots use
local JSON export.

## Configuration, failures, and limitations

This feature does not edit stored memories or provide database persistence.
Search affects the displayed snapshot, not retrieval rank. On narrow screens,
navigation/table/details stack using responsive styles. Stale async requests are
guarded when switching sessions. A fresh chat without server state displays empty
memory; lost state for a started chat displays unavailable memory and requires a
new chat to continue. Inspection/export does not reconstruct evicted or lost records.

Timing values are seconds. Agent usage is separate from memory LLM usage; local
embedding arrays/model RAM are excluded from logical storage snapshots. Full
context lives outside NoMemory, so module counts are zero despite a supplied
transcript. See [results and resume](../benchmark/results_and_resume.md) for metric
definitions and snapshot persistence.

## Source and verification

[workspace.js](../../src/workspace.js), [index.html](../../src/index.html),
[style.css](../../src/style.css), [app.py](../../src/app.py), and
[Diagnostics.py](../../src/Diagnostics.py) implement the feature.
[Diagnostics tests](../../tests/test_diagnostics_benchmark.py) and
[frontend state tests](../../tests/test_frontend_state.py) cover snapshots,
turn selection, isolation, and stale session state.
