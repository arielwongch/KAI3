<!-- Historical document; see the notice below before interpreting its status. -->
> Historical record, archived on 2026-10-08 from `spec/ui_refinement_plan.md`.
> First recorded in Git: 2026-10-05, commit `acb7a6f`. This is a commit date,
> not a verified proposal/approval or deployment date. The body preserves the
> pre-reorganization working-tree text, including later edits and old status claims.
> "Current", "planning only", dates, and open questions below describe that
> historical document and are not current project status.
> See the [plan index](../README.md) for reconciled status and the
> [specification index](../../spec/README.md) for implemented behavior.

# KAI3 UI Refinement Plan

## Status

Planning only. This document proposes a focused redesign of the Benchmark and
Chat workspaces. No application code has been changed for this refinement.

## Goal

Make Benchmark easier to configure and understand, and make Chat feel calmer
and more polished. Keep the current memory architectures, benchmark protocol,
scoring, judge, inspector data, exports, and cancellation behavior.

## Current UI issues

- Benchmark setup and output share one long scrolling page. Configuration,
  progress, calibration, memory inspection, and every question's raw JSON appear
  together.
- Most output is rendered as JSON in generic cards. Important scores and failed
  cases do not have a clear visual hierarchy.
- Dataset selection, conversation/category filters, run buttons, and estimated
  calls are not grouped into a guided setup flow.
- Chat header repeats workspace links; sidebar, module selection, status, and
  inspection actions compete for attention.
- The memory inspector is a narrow drawer with a table and details appended in
  place, which makes it difficult to browse larger stores.

## Design direction

Retain KAI3's dark charcoal surfaces, muted typography, and lime accent, but use
more whitespace, fewer simultaneous controls, consistent section headings, and
clear primary actions. Keep the same design language across landing, Chat,
Benchmark setup, and Benchmark results.

## Benchmark redesign

### 1. Separate setup, active run, and results states

Use one Benchmark workspace with three deliberate states:

1. **Setup** — configure and review a run.
2. **Running** — focus on progress, current phase, cancellation, and partial
   status.
3. **Results** — show the completed or partial report; keep setup available as
   a secondary action to start another run.

Avoid showing the full setup form and full report at the same time. Keep the
uploaded dataset and selected settings in page state while moving between states.

### 2. Make setup a compact form with grouped steps

- **Dataset**: large drag/drop or browse area; show file name, size, and parsed
  conversation count after upload.
- **Memory architecture**: four single-select tiles with short plain-language
  descriptions. Keep the one-module-per-run rule clear.
- **Questions**: choose all or selected conversations, categories, and a
  question limit. Parse the dataset first, then offer actual conversation IDs
  in a searchable multi-select rather than a free-form comma-separated field.
- **Evaluation**: show DeepSeek answer and judge models and the four judge
  dimensions as concise read-only settings. Keep less common settings collapsed
  under Advanced.
- **Run summary**: a visually distinct compact card with selected module,
  conversations, question count, answer/judge call estimates, and scoring
  methods. Put one prominent **Run benchmark** action beside it.

### 3. Give the active run a clear progress view

Show run status, completed/total questions, a progress bar, current architecture
and conversation, and a concise phase label (ingesting, answering, judging, or
finalizing). Keep Cancel available while active. When cancelled or failed, make
partial-result availability explicit and lead into the partial report.

### 4. Turn results into a readable report

- Begin with a compact status banner and run configuration summary.
- Show metric cards for LoCoMo score, normalized exact match, token F1, judge
  score, answer completion, and judge completion. Include valid counts beside
  averages and distinguish unavailable values from zero.
- Use a category summary table or chart with readable category names and IDs.
- Add filters for category, answer status, judge disagreement/uncertainty, and
  evidence availability.
- Render a question table with question, category, prediction status, principal
  scores, and judge status. Expand a row to reveal reference answer, prediction,
  retrieved evidence, judge dimension scores and rationale, human review, and
  per-question timing/token details.
- Keep Export results, Export human review sample, Import reviewed labels, and
  Inspect ingested memory in a clearly grouped secondary-actions menu/section.
- Show calibration status and agreement in a compact panel; move detailed
  review notes into the expanded question view.

## Chat refinement

- Simplify the header to page identity, selected memory architecture, and one
  obvious Memory button. Move Home/Chat/Benchmark navigation into a consistent
  sidebar or compact workspace switcher instead of repeating links.
- Keep recent conversations and New chat in the sidebar, but improve active,
  hover, and empty states. Give long chat names a one-line truncation treatment.
- In an empty chat, present a concise welcome and five memory architecture
  cards with one-sentence descriptions. After selection, show the chosen
  architecture as a small status chip that cannot be mistaken for a live
  selector; changing architecture starts a new chat.
- Improve message spacing, readable line length, code block contrast, and
  loading/error states. Keep Markdown sanitization and copy controls.
- Refine the composer into a stable bottom-aligned surface with a clear focus
  state, useful placeholder, accessible send action, and compact selected-memory
  label. Preserve Enter/Shift+Enter behavior.
- Replace the narrow inspector drawer with a wider database workspace or
  full-height split panel. Use a three-pane browsing pattern where space allows:
  memory collection/navigation, record table, and selected-record details.
  Retrieved context and metrics should be separate views tied to a selected turn.
  On smaller screens, use stacked navigation/table/detail screens with a clear
  Back action.

## Shared interaction and visual rules

- One primary action per view; secondary actions should be visually quieter.
- Use consistent page titles, section spacing, button sizes, status colors, and
  focus outlines.
- Replace raw object dumps with labeled fields, tables, metric cards, and
  expandable technical detail. Keep a raw JSON view/export for diagnostics.
- Keep long content scrollable within the correct workspace region. Avoid
  nested scroll areas unless the data table needs its own horizontal scroll.
- Preserve responsive behavior and keyboard access for menus, filters, tables,
  dialogs, and file inputs.

## Proposed implementation phases

1. Confirm visual direction and the desired amount of benchmark setup guidance.
2. Refactor Benchmark markup and state transitions into setup/running/results.
3. Build the metric summary, category breakdown, filtered question table, and
   expanded per-question report.
4. Redesign Chat navigation, empty state, memory selection/status, messages,
   composer, and database inspector layout.
5. Consolidate responsive styles and accessible interaction states; remove
   obsolete styles and controls.
6. Update `spec/frontend.md` and README screenshots/descriptions if applicable;
   inspect desktop, narrow viewport, empty, running, partial, failed, and
   completed states.

## Acceptance criteria

- Benchmark setup, active progress, and results are visually distinct states.
- A user can configure a run without interpreting raw configuration JSON or
  typing conversation IDs manually.
- Results make the key scores, denominators, failures, and judge outcomes
  understandable at a glance; technical details remain available on expansion.
- Human review, export, import, cancellation, and memory inspection remain easy
  to find without dominating the main report.
- Chat has a clear primary interaction, an obvious selected memory mode, and a
  less crowded navigation header.
- Memory browsing makes collection, record list, and record details clear, with
  a usable small-screen layout.
- No change to benchmark scoring or memory behavior is introduced by this UI
  refinement.

## Planning choices to confirm

1. Keep the existing dark charcoal/lime theme, or use a lighter dashboard style?
2. For Benchmark results, prefer a compact table and metric cards, or a more
   visual dashboard with charts plus the per-question table?
3. Should the memory database open as a full-screen workspace or stay as a
   right-side panel on desktop?

The proposed default is to retain the dark theme, use metric cards plus a
category table and expandable question list, and make the memory database a
wide split workspace that becomes stacked screens on mobile.
