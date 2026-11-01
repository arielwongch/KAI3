# Shared workspace shell

Status: implemented behavior. Focused source and browser verification: 2026-11-02.
This is not a release date or a comprehensive accessibility acceptance result.

## Ownership and navigation

Chat (`/chat`), Test Benchmark (`/benchmark`), and Compare Runs (`/compare`) render
the same `workspace_sidebar` Jinja macro. It supplies KAI3/Home branding, the
three workspace links in one navigation group, active-page/`aria-current` state,
collapse control, page-specific sidebar content, and the local-workspace footer.
Workspace links are separated from actions such as New chat/New benchmark.

Chat retains recent chats; Benchmark retains New benchmark and saved runs;
Compare has Result library/Run comparison anchors. Sidebar content is distinct
from the full-height [memory inspector](memory_inspector.md).

## Layout and design

`style.css` owns the charcoal/lime tokens, DM Sans body text, Space Grotesk
headings/branding, sidebar, buttons, and workspace layout. Compare loads those
styles before its scoped `compare.css`, adopts the benchmark-style header and
internal content scroller, and sizes its library/charts to the available width.
Feature-specific interactions belong to [Chat](chat.md),
[Benchmark](benchmark.md), and [Compare Runs](compare_runs.md).

Desktop navigation is 252px wide, collapsing to 76px. The `kai-app` container and
720px mobile breakpoint select the compact drawer. Compare's content container
stacks charts, cards, and controls below 680px of available content width.

## Sidebar interactions

`workspace-shell.js` owns sidebar behavior for all three pages:

- Desktop collapse updates width, icon, accessible label, and expanded state.
- Mobile open activates the drawer/backdrop, expands a previously collapsed
  sidebar, and focuses the active workspace link.
- Backdrop, Escape, the mobile collapse control, or a navigation link closes the
  drawer. Escape respects open native dialogs; dismissal can restore opener focus.
- Closed mobile navigation is inert. While the drawer is open, workspace content
  is inert; returning to desktop clears the drawer/background-blocking state.

Sidebar state is page-local; it is not persisted across navigation/reload. Feature
state such as chat history and result selection retains its own documented rules.

## Assets and verification

[Template](../../src/workspace_sidebar.html), [navigation script](../../src/workspace-shell.js),
[styles](../../src/style.css), [Chat/Benchmark template](../../src/index.html), and
[Compare template](../../src/compare.html) implement the shell. `app.py` allows
the shared script/styles as public assets; the Jinja template and private source/
configuration files are not public static assets.

Headless Chrome checked 1440px/390px layouts, all three link groups, shared fonts,
expanded/collapsed widths, mobile open/dismissal, and content focus blocking, with
no JavaScript errors. The 15 targeted result tests and 14 frontend state tests
passed after integration; the shell itself was exercised in-browser. Full
keyboard/screen-reader/accessibility and cross-browser acceptance remains open
in the [UI plan](../../plans/ui_refinement.md).
