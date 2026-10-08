# Chat workspace

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

## Purpose and page structure

Flask serves a landing page at `/` with Chat and Test Benchmark destinations.
`/chat` renders `index.html` with the chat workspace selected. The dark charcoal
and lime interface has workspace navigation, recent chats, a selected-memory
status, a scrolling message area, and a bottom composer. The
[memory inspector](memory_inspector.md) is a separate full-height workspace.

## Stored browser and server state

`workspace.js` stores `{version: 1, sessions, active}` in localStorage under
`kai3-workspace-v1`. Sessions contain ID, title, module, messages, and started state.
The legacy `kai3-chat-history`, `kai3-chat-id`, and `kai3-memory-module` keys are
migration inputs, not the canonical current store. New chat appends an independent
session; it does not erase all previous sessions. Selecting a history entry
switches the active chat and its inspection state.

Server `ChatSession` instances hold one memory module, a lock, and turn diagnostics
per chat ID. They are process-local. Restored browser messages are not replayed
into memory after restart. The client checks server availability and disables
continuation for lost memory, prompting a new chat.

## Write and interaction flow

Select one of `no_memory`, `sliding_window`, `summarization`, `vector_store`, or
`fact_store` before sending. Selection locks for that chat; another architecture
requires a new chat. The composer is disabled until selection or while sending,
checking memory, or unable to reconnect. Enter sends; Shift+Enter inserts a newline.

The client sends a user message to `/get`, renders the returned assistant message,
persists browser state, and refreshes diagnostics. User content uses text nodes.
Assistant Markdown uses `marked` then `DOMPurify`; code blocks have copy controls.
Pending and failed requests have visible states. Memory behavior belongs to the
[memory components](../README.md) and [agent interface](../memory/interface.md).

## API and configuration

`POST /get` receives JSON with `message`, `chat_id`, `memory_module`, and optional
`requires_existing`. IDs must be nonblank strings up to 200 characters; mode must
be known; message must be nonblank. Success includes `reply`, `latency`, `tokens`,
the implementation class in `memory_module`, and `turn_id`.

| Outcome | HTTP status |
| --- | --- |
| Invalid payload/message/chat ID/mode | 400 |
| Existing chat requested with another mode | 409 |
| `requires_existing` but server memory was lost | 410 |
| Agent/model/embedding/extraction failure | 503 |

Requests for one chat are serialized. Turn diagnostics are appended even on
failure. Diagnostics/export endpoints are specified in
[memory inspector](memory_inspector.md).

## Responsive behavior and limitations

Workspace content scrolls within the viewport. The `kai-app` CSS container
controls compact layouts, including off-canvas sidebar navigation and flexible
conversation/composer widths. Browser storage preserves visible history, not
server memory or a durable continuation guarantee. The current implementation
has no user-facing chat token-budget/capacity editor.

## Source and verification

[home.html](../../src/home.html), [index.html](../../src/index.html),
[workspace.js](../../src/workspace.js), [style.css](../../src/style.css), and
[app.py](../../src/app.py) implement the UI and endpoints.
[Frontend state tests](../../tests/test_frontend_state.py) and
[memory integration tests](../../tests/test_memory_integration.py) cover state and
API behavior. Visual acceptance history belongs to the [UI plan](../../plans/ui_refinement.md).
