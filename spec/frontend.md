# Frontend Specification

## Overview

KAI3 provides a landing page and separate dark, memory-first Chat and Test Benchmark workspaces. Flask serves `/` from `src/home.html` and `/chat` and `/benchmark` from `src/index.html`, styled in `src/style.css`.

The interface contains a compact navigation sidebar, a centered conversation view, and a persistent floating composer. The visual system uses charcoal surfaces, muted text, lime accent states, rounded controls, and subtle entrance/loading animations.

## Layout

The home page links to two workspaces. Chat is organized into two primary regions:

- **Sidebar**
  - KAI3 brand mark
  - New chat control
  - Recent chat history
  - Local workspace status and user avatar
  - Collapsible expanded and icon-only states
- **Main chat stage**
  - Model/status header
  - Empty-state prompt when no messages exist
  - Scrollable conversation history
  - Fixed composer area at the bottom

The page is locked to the viewport. Document scrolling is disabled; conversation content scrolls inside the chat area. Scrollbars use the same dark charcoal palette as the rest of the interface.

## Chat Composer

The composer is the primary interaction surface and includes:

- Multi-line text input
- Enter-to-send behavior
- Shift+Enter for a newline
- Memory module selector
- Circular send button
- Loading indicator while the API request is pending
- Disclaimer text below the composer

The available memory modes are:

- `no_memory`
- `sliding_window`
- `summarization`
- `vector_store`
- `fact_store`

The mode is selected before the first message and locked for that chat. The
selected mode and chat ID are sent with each request.

## Messages

Messages are stored as objects with a `role` and `content` value. User and assistant messages have distinct avatars, labels, and visual treatments.

Assistant messages support Markdown through `marked`. Rendered output is sanitized with `DOMPurify` before insertion into the page. Fenced code blocks receive a copy control backed by the browser Clipboard API.

A typing indicator is displayed while the Flask request is in progress. Request failures are rendered as assistant-side error messages so the conversation remains usable.

## Browser Persistence

Conversation messages are persisted in `localStorage` under the key `kai3-chat-history`.

On page load, stored messages are restored and rendered. Starting a new chat clears the current browser-backed conversation and returns the interface to its empty state. The first user message is used as the current chat label in the sidebar history.

## Responsive Behavior

The `.app-shell` element is a named CSS container (`kai-app`). Responsive rules use container queries rather than relying only on viewport width. This allows the interface to adapt to the width available to its containing element.

At compact container widths:

- The sidebar becomes an off-canvas panel
- A mobile menu control is shown
- Conversation and composer widths use the available container space
- Suggestion buttons stack vertically
- Nonessential composer hint text is hidden
- Heading sizing uses container-relative units

The conversation and composer use flexible sizing with bounded maximum widths, allowing the chat to remain centered on wide displays and usable in narrow layouts.

## Flask API Integration

The frontend sends chat requests to:

```http
POST /get
Content-Type: application/json
```

Request payload:

```json
{
  "message": "User message",
  "chat_id": "browser-generated-chat-id",
  "memory_module": "sliding_window"
}
```

The Flask route validates the message, chat ID, and memory mode, reuses or creates
a memory instance for that chat, and invokes `run_ReAct`. Server memory is isolated
by chat ID and cleared on process restart; browser history is not replayed.

Successful responses include:

```json
{
  "reply": "Assistant response",
  "latency": 0.42,
  "tokens": 128,
  "memory_module": "SlidingWindow"
}
```

Invalid requests return HTTP 400. Changing a chat's memory mode returns HTTP 409.
Model, embedding, extraction, or server failures return HTTP 503 with an error message.

## Frontend Files

- `src/index.html`: page structure, interaction logic, localStorage handling, API calls, Markdown rendering, and loading states.
- `src/style.css`: theme, layout, responsive container queries, scrolling behavior, controls, message styling, code blocks, and animations.
- `src/app.py`: Flask page route and JSON chat endpoint consumed by the frontend.


## Session workspace and testing

`src/workspace.js` owns versioned browser session state and migrates the legacy
single-chat keys. Sidebar entries switch active sessions. Restored histories
check the server before enabling the composer; lost memory requires a new chat.

The header's Memory database control opens a responsive panel with a database-
style record grid, searchable text/metadata, record details, Retrieved context,
and Metrics views, a turn selector, refresh, and JSON export.
It consumes `/api/chats/<chat_id>/diagnostics` and refreshes after failed turns
as well as successful ones. Inspected data is rendered with text nodes.

The Benchmark workspace separates setup, active progress, and the final/partial
report. Setup parses the uploaded LoCoMo dataset, exposes searchable conversation
choices and category filters, selects one architecture, and estimates answer and
judge calls. QA uses direct memory retrieval and one normal conversational API
call without ReAct or memory write-back; DeepSeek judges each prediction. The
report leads with metric cards and a category table, then provides filters and
expandable question details. Cancellation, JSON export, human review export and
import, and ingested-memory inspection remain available.

The memory database is a full-height workspace. It provides stored records in a
searchable table with a selected-record detail pane, plus separate retrieved
context and metrics views tied to the selected turn. On narrow screens the
navigation, table, and details stack vertically.
