# Benchmark module selection: reproduced scroll jump and fix plan

Date: 2026-11-10. Status: user approved implementation; CSS fix and browser
regression are implemented locally. The original diagnosis is retained below.
Existing local compaction/startup changes are preserved.

## Reproduction

Run an isolated Chrome instance against a synthetic fixture that renders the
current `src/index.html`, stylesheet, workspace JavaScript, and architecture
capabilities. No benchmark jobs, paid API calls, or user result mutations occur.

1. Open `/benchmark` in a fresh page.
2. Scroll `.benchmark-scroll` until Epsilon or Compaction is visible.
3. Click the visible architecture label using actual mouse input.
4. The header/sidebar and application shell move upward, leaving blank space
   below the shortened visible application.
5. Attempt to scroll back up normally. The outer document remains displaced;
   refreshing resets it.

Reproduced at 1440x700, 1440x900, 2048x950, and 390x844 CSS-pixel viewports.
The size of the jump depends on viewport height and selected card position.
Epsilon need not jump at taller heights where its invisible input is already
within the viewport; Compaction is farther down and more readily triggers it.

Representative measurements at 1440x700:

| Selection / temporary treatment | Root scroll before | Root scroll after click | Shell top after click | Root scroll after wheel up |
| --- | ---: | ---: | ---: | ---: |
| Epsilon / current CSS | 0 | 428 | -428 | 428 |
| Compaction / current CSS | 0 | 428 | -428 | 428 |
| Epsilon / change handler disabled | 0 | 428 | -428 | 428 |
| Compaction / change handler disabled | 0 | 428 | -428 | 428 |
| Epsilon / card `position: relative` | 0 | 0 | 0 | 0 |
| Compaction / card `position: relative` | 0 | 0 | 0 | 0 |

With the CSS treatment, upward wheel scrolling correctly returns the inner
benchmark scroller to zero. Current CSS also produced root shifts of 985 pixels
for Epsilon and 1,209 pixels for Compaction at 390x844. The controls remain
selected, so this is a layout/focus problem rather than failed selection.

## Confirmed cause

`src/style.css` makes `.architecture-option input` absolutely positioned and
transparent. Its visible parent label `.architecture-option` lacks a positioning
context. The input's `offsetParent` is therefore BODY rather than the card.
Its invisible focus rectangle does not follow the visible label correctly when
the inner benchmark pane scrolls.

At 1440x700 before selection, the Epsilon label was near y=385 while its input
was near y=865; Compaction's label was near y=385 while its input was near y=1032.
Native label activation focuses that input. Chrome scrolls the outer HTML
document to reveal it, despite `overflow:hidden`. The application shell keeps
its original height but its top becomes negative. This explains both the
missing header/sidebar and the blank area below.

Normal wheel input does not undo the outer focus-induced scroll: the application
uses a separate internal scroll pane, and the outer document has no ordinary
scrollbar. Disabling the module change handler did not prevent the jump. A
browser-only stylesheet injection setting the card to `position:relative`
changed the input's offset parent to LABEL and eliminated the outer scroll.
The input's focus rectangle then remained inside the visible card.

The previous compaction UI smoke check selected radios by setting `checked`
and dispatching `change`; this did not exercise native label focus. Its document
width assertion also could not detect vertical document displacement. The
regression test must cover real pointer/focus behavior and vertical geometry.

## Proposed implementation

1. Add `position: relative` to the shared `.architecture-option` rule in
   `src/style.css`, containing each hidden native radio within its visible card.
   The one-property treatment already removed the jump across the tested
   desktop/mobile sizes. Explicitly bounded hidden-radio geometry was also
   tested successfully, but the minimal containing-block correction is enough
   for the observed issue.
2. Preserve native radio semantics, label activation, keyboard navigation,
   selected styling, and card focus outlines. Module settings/payloads remain
   governed by the current change handlers.
3. Add a reproducible browser regression using real label clicks. Assert
   `document.scrollingElement.scrollTop === 0`, application-shell top === 0,
   header/sidebar geometry, successful selection, and correct settings-panel
   visibility. Allow the benchmark pane itself to scroll normally.
4. Cover short and tall desktop viewports, phone width, switching between
   lower and upper cards, repeated selection, keyboard Tab/arrow navigation,
   and sidebar collapse. Check navigation back to the top without refreshing.
   Verify the root document remains viewport-height after selection.
5. Run the affected frontend checks and desktop/mobile browser regression,
   then visually verify header, sidebar, architecture cards, and relevant
   settings. No provider-backed benchmark is needed for this CSS fix.

Acceptance: selecting any architecture leaves the application shell anchored
to the viewport; ordinary inner scrolling can reach both ends; keyboard focus
and module configuration still work. No refresh is needed to recover layout.

## Diagnostic artifacts

Ignored local artifacts under `instance/`:

- `scroll_preview.py`: synthetic, dependency-light fixture server.
- `reproduce_scroll.js`: actual mouse input across three viewport sizes and
  current/relative-card/bounded-radio stylesheet treatments.
- `reproduce_scroll_short.js`: 1440x700 reproduction and change-handler control.
- `scroll-reproduction.json` and `scroll-reproduction-short.json`: before/after/
  wheel measurements of every relevant ancestor, label, and radio.
- `scroll-baseline.png` and `scroll-relative-only.png`: visually inspected
  broken versus temporary corrected layout at 1440x700.

During diagnosis, twenty-four browser scenarios completed without JavaScript
exceptions. The initial CSS treatments existed only in isolated browser documents;
the application stylesheet was unchanged at that stage.

## Approved implementation and validation

Added `position:relative` to the shared `.architecture-option` rule, anchoring
each invisible native radio to its visible card. No JavaScript scroll correction
or module-setting change is required.

The reusable [browser regression](../tests/test_benchmark_scroll_browser.js)
uses the real templates/styles/scripts and an isolated
[synthetic fixture](../tests/fixtures/benchmark_browser.py). It covers every
architecture, repeated lower/upper-card selection, native Tab/arrow navigation,
wheel scrolling to both ends, and expanded/collapsed desktop sidebars. Viewports:
1440x700, 1440x1000, 2048x950, and 390x844. Results: 140 real clicks, 112 keyboard
selections, and 266 geometry checks passed, without JavaScript exceptions. Root
scroll and shell/header/sidebar displacement remained zero. A browser-only
reversion to `position:static` made the regression fail, confirming sensitivity.

The 34 Node frontend cases and comparison UI checks passed. This is focused
validation for the CSS change, not a fresh full Python-suite run. No provider
calls or user-result changes were made. Changes remain local/uncommitted.
