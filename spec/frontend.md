# Frontend Specification

## Overview

KAI3 provides a dark, memory-first chat workspace inspired by modern conversational interfaces. The frontend is served by Flask from `src/index.html` and styled in `src/style.css`.

The interface contains a compact navigation sidebar, a centered conversation view, and a persistent floating composer. The visual system uses charcoal surfaces, muted text, lime accent states, rounded controls, and subtle entrance/loading animations.

## Layout

The application is organized into two primary regions:

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

- `sliding_window`
- `summarization`

The selected mode is sent with each chat request.

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
  "history": [
    {"role": "user", "content": "Previous message"},
    {"role": "assistant", "content": "Previous reply"}
  ],
  "memory_module": "sliding_window"
}
```

The Flask route validates the message and memory mode, converts recent browser history into agent memory context, and invokes `run_ReAct`.

Successful responses include:

```json
{
  "reply": "Assistant response",
  "latency": 0.42,
  "tokens": 128,
  "memory_module": "SlidingWindow"
}
```

Invalid requests return HTTP 400. Model or server failures return HTTP 503 with an error message.

## Frontend Files

- `src/index.html`: page structure, interaction logic, localStorage handling, API calls, Markdown rendering, and loading states.
- `src/style.css`: theme, layout, responsive container queries, scrolling behavior, controls, message styling, code blocks, and animations.
- `src/app.py`: Flask page route and JSON chat endpoint consumed by the frontend.
