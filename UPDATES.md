# Updates

## Align ingestion accounting and release unused initialization resources - 2026-11-04

Headline and lifecycle token accounting now share ingestion deduplication rules
in Python and the browser. Reused ingestion IDs with conflicting provider
provenance or conversation ownership leave complete totals and known subtotals
unavailable; identical builds count once regardless of JSON property order.

Per-chat initialization locks now expire when no request retains them, including
missing restored chats and failed construction. Temporal batch staging copies
mutable entries while sharing read-only embedding vectors, preserving rollback
without repeatedly copying vector arrays. Regression coverage exercises conflict
handling, lock lifetime, and metadata isolation across failed and successful batches.

Verification: all 247 offline Python tests, 31 frontend state checks, and the
import/export regression suite passed. JavaScript syntax and whitespace checks
passed. No provider-backed calls were made.

## Complete report-level usage and storage qualifiers - 2026-11-04

Finished the remaining reporting scope in live and imported Benchmark reports.
The report now displays known memory-plus-answering and lifecycle token lower
bounds, missing-request and missing-failure coverage, incomplete/legacy phase
records, and deduplicated ingestion-build counts. Conflicting builds keep known
subtotals unavailable. Memory details distinguish current snapshots from latest
successful retained ingestion storage, including selected-conversation coverage.
Local imports now flag filename/config mismatches directly without network
access or source mutation. These qualifiers match the Compare Runs interpretation.

Added regressions for displayed fields, judging scope, duplicate/conflicting
builds, incomplete storage cohorts, Unicode text bytes, filename changes, and
preservation of imported data. Provider experiments and human adjudication remain
outside this reporting-only follow-up.

Verification: 30 frontend state checks, the import/export regression suite and
its Python wrapper, and comparison UI checks passed. All three saved periodic
summary exports rendered through the complete import/export path. Fixed optional
saved-export test isolation so later assertions use their original fixture.
Whitespace checks passed; original saved result files remain unchanged.

## Validate the 4 November decision brief and qualify comparison costs - 2026-11-04

Reproduced the periodic-summary scores (36, 34, and 35 correct out of 100),
matched settings, and recorded usage subtotals. Confirmed that the filename
claiming window 100 actually configures 50, interval 20 records 15 ingestion
builds and only three current snapshots, and the blinded 84-response template
has no actual human labels. The vector/reranker refresh changes only derived
comparison data. Research descriptions were checked against the linked primary
sources; they do not validate KAI3's configuration.

Comparison schema 6 keeps complete provider-token totals unavailable when any
required request usage is missing, including failed attempts. Known recorded
usage is a separate lower bound with missing-failure, request, record, and
legacy-ledger coverage. Headline memory-plus-answer totals exclude judging;
lifecycle totals include it. Live/imported report calculations follow the same
unknown-usage rule. Original request ledgers and saved export bytes are preserved.

Library analysis flags filename/config mismatches without renaming or rewriting
files. Storage charts identify current-snapshot scope and conversation coverage;
latest retained successful-ingestion storage is separately available across
current and previous builds. Updated the audit plan's superseded packing and
query-only cost descriptions. Actual blinded adjudication remains next, followed
by the frozen standalone reranker confirmation and independent periodic-factor
experiments. No human labels or new provider-backed experiments were generated.

Verification: all 242 offline Python tests, 30 workspace frontend checks, and
the comparison UI checks passed. Whitespace checks passed. Original saved result
files have no diff.
See [validation, evidence, and remaining fix plan](plans/decision_brief_2026-11-04.md).

## Repair versioned windowed fact extraction - 2026-11-04

Versioned fact batches now use explicit local result handles resolved by Python,
including deduplicated assertions, instead of asking the model to predict numeric
version IDs. A standalone batch prompt defines ordered results and reference
scope. Extraction sends compact complete fact state while retaining full stored
provenance; the saved conv-50 version payload shrank by 80.5% in UTF-8 bytes.

Malformed or truncated batches receive one bounded repair from the original
snapshot. Terminal failures preserve both memory tiers and pending entries.
Private failure artifacts under ignored `instance/memory_failures/` capture raw
responses, input, provider metadata, and structured validation locations. Memory
requests have separate byte/output limits, and repair calls count toward usage.
Reports identify ingestion failures, including older saved reports; prompt and
extraction-policy identities prevent incompatible resume.

Validation: the 234-test Python suite passed, followed by 24 final targeted
memory/recovery tests and 29 frontend state checks. Whitespace checks passed.
All validation used offline fixtures; no new provider-backed benchmark was launched.
See [investigation and fix plan](plans/windowed_fact_store_failure.md) and the
[periodic memory contract](spec/memory/periodic_window.md).

## Refine workspace readability and chat responsiveness - 2026-11-03

Refined the existing Flask frontend with a functional charcoal/lime palette,
higher-contrast secondary text, a 12px minimum for small labels, and consistent
4/8px spacing for cards and form groups. Removed decorative section numbering
from benchmark setup and Compare Runs. Added shared hover/pressed feedback,
keyboard focus treatment for file/radio containers, reduced-motion handling,
accessible chat input/group labels, and selected-memory pressed state.

Memory-module construction now uses per-chat initialization locks outside the
global registry lock. Slow model/tokenizer setup no longer holds up unrelated
chats or their diagnostics. Concurrent first messages still share one memory
module. Flask request threading is explicit; benchmark workers and asynchronous
browser requests retain their existing execution paths.

Verification: all 225 offline tests passed, including two new concurrency
regressions. All 28 workspace frontend state checks passed. Isolated headless
Chrome rendered Chat, benchmark setup, and Compare Runs at 1440px and 390px;
page-level horizontal overflow and visible-text contrast checks passed in those
views. Screenshots were inspected. These scoped checks do not establish full
WCAG conformance or cover every report, dialog, and assistive-technology state.
No live model/API calls were made.

## Handle damaged tokenizers and reuse report context counts - 2026-11-03

Malformed locally cached tokenizer artifacts now leave context metrics unavailable
instead of failing report analysis or unbounded benchmark answering. Native parse
errors are handled at the tokenizer-loading boundary, without model calls or
downloads.

Context counts are reused across overall and category calculations within each
report. The process-wide cache of full context strings was removed. A regression
with 1,200 distinct contexts plus a duplicate verifies exactly 1,200 encodes per
analysis, including a second analysis with fresh report-local counts. Recorded
counts retain precedence over derived counts.

All 223 offline tests passed, including malformed-artifact fallback, duplicate
context reuse, and recorded-count precedence. Patch whitespace checks passed.

## Align Benchmark breakdown with Compare lifecycle totals - 2026-11-03

Benchmark Reported API tokens now includes known consumption from failed answer
or judge calls, including calls without a parsed result. Recorded processing time
uses cumulative execution timing, matching Compare Runs. Memory and ingestion
totals also follow per-module lifecycle rules for duplicate builds, conflicting
records, and unknown measurements. Headline averages retain their existing
definitions and continue to exclude judging where specified.

All 126 checks across 18 saved reports matched the current Compare calculations.
The two reranker API totals are now 227,169 and 326,295 tokens, correcting omitted
judge usage. All 30 frontend checks passed, with regressions for failed calls,
cumulative timing, duplicate IDs/key ordering, and unavailable/conflicting data.
This fixes display calculations; saved source records were not changed.

## In-chart legend and table copying - 2026-11-03

Moved the run/color legend inside the chart card, wrapping above the plot.
Added independent copy controls for all four Compare Runs tables, with TSV,
formatted HTML plus plain-text fallback, and Markdown formats. Copies preserve
displayed row order and headers/main values while omitting secondary notes and
small counts. Empty/pending states, clipboard failures, escaping, and feedback
are handled without modifying saved reports.

The 30 frontend checks passed, including all formats, notes omission, duplicate
copy prevention, and clipboard denial. Isolated Chrome at desktop/phone sizes
verified twelve long run labels, the legend's position above the plot, sorted
copy payloads, all four controls, and no JavaScript exceptions. Clipboard writes
were stubbed so the system clipboard remained untouched; screenshots were
visually inspected. No provider calls or saved-result changes were used.

## Separate context size from provider-token cost - 2026-11-03

Benchmark reports now show Context tokens/question alongside Memory + answering
tokens/question. Compare Runs offers both as independent axis choices and displays
their separate coverage. Context is only the supplied conversation/memory text;
it excludes question/instructions/output and uses the fixed benchmark tokenizer.
The current memory-plus-answering calculation is retained, including its rule for
ignoring unreported failed-request usage.

Comparison version 5 prefers recorded context counts and can count exact saved
context with the pinned local tokenizer, without model calls or downloads. Padding
and truncation are disabled. Empty context is zero; absent context text/counts
remain unavailable rather than using whole-prompt or byte estimates. Completed
saved-run analysis and library views expose the derived context metric without
changing original source records.

All 18 saved comparisons were refreshed with existing provider-cost averages
unchanged. Thirteen reports have context counts; five older exports lack both
counts and exact supplied context and remain unavailable for context only.
Offline tokenization matched all 1,200 existing recorded context counts. All 220
offline tests and 30 frontend checks passed. Desktop/phone Chrome verified
separate 200-context-token and 110-provider-token fixture averages, context-axis
selection, and absence of JavaScript exceptions.

## Ignore failed requests with unreported token usage - 2026-11-03

Per the requested counting rule, token averages now ignore failed requests with
no reported tokens. Failed requests with known usage still count; successful or
in-progress requests with missing usage remain unavailable. The rule is shared
by Benchmark reports and Compare Runs and recorded in comparison version 4.
Original request ledgers remain intact. This supersedes the strict failed-request
handling described in the investigation below.

Refreshed all 18 saved reports to version 4 and verified their source records are
unchanged. Windowed Summary k=10 now reports 36,527.20 tokens/question; k=100
reports 11,882.34. Frontend calculations match every saved report. All 213 offline
tests and 30 frontend checks passed; no provider calls were made.

## Verified unavailable token averages - 2026-11-03

Audited all 17 result-library reports. Fifteen have complete memory-plus-answer
usage. Windowed Summary k=10 has one memory retry with unknown usage (conv-43);
k=100 has two memory retries (conv-30/conv-44) and one answer retry (conv-30,
question index 7) with unknown usage. These attempts failed without token or
prompt/completion counts, then succeeded on retry. Successful-response counters
exclude the unknown attempts and cannot establish the full total.

Both original saved runs contain the same records as their exports, so the missing
usage cannot be recovered from those snapshots. Known recorded tokens establish
lower bounds of 36,527.20 and 11,882.34 tokens/question respectively, not exact
averages. The exact values correctly remain unavailable. Frontend and backend
calculations agreed on all 17 actual reports; all ten focused cost tests passed,
including unknown memory/answer retries and judging-only failure isolation. No
provider calls or result-file changes were made during this investigation.

## Memory and answering cost per question - 2026-11-03

Benchmark reports and Compare Runs now divide total memory + answering provider
tokens by recorded question count, excluding judging. Average runtime divides
total recorded memory preparation + retrieval + answering time by that count,
also excluding judging. This replaces answer/judge-only token averages and means
computed over only questions with measured timing. Unknown required usage remains
unavailable. Recorded rebuilds, query retries, and preparation without questions
remain in the overall cost; shared conversation costs are allocated before
category filtering.

New runs record preparation including module setup; old reports use their recorded
ingestion totals without estimating missing setup time. Comparison schema version
3 recomputes derived metrics without changing source predictions or judge labels.

Verification: all 208 offline tests passed, including seven new cost-accounting
regressions; 30 frontend checks also passed. Isolated Chrome at desktop/phone
sizes confirmed identical 110 tokens/question and 26/3 seconds/question in the
Benchmark report and Compare Runs despite exaggerated judging costs. No provider
calls or saved-result modifications were used for browser verification.

## Loading indicators and selected saved run - 2026-11-03

Startup follow-up: bundle the loading helper into the existing workspace scripts
and create the status element when absent from a cached template. This fixes
`KAI3Loading is not defined` on servers started before the new asset was registered,
without restarting an in-process benchmark. Refresh the browser to load the fix.
All 30 frontend checks passed, and isolated desktop/mobile Chrome verified a
simulated older template with no helper tag or loading-status element.

Chat, Test Benchmark, and Compare Runs now show small inline spinners during
loading, imports, downloads, saves, and pending actions. Saved runs show Loading
while opening, then retain a sidebar highlight. Active benchmark
progress uses one continuous spinner without flashing on background refreshes.
Failures clear indicators, and late responses cannot restore a run after switching
or resetting the view. Shared indicators respect reduced-motion preferences.

Verification: 29 frontend regression checks passed, plus the related Python
result-library/frontend checks. Isolated Chrome desktop/phone checks and screenshot
review covered all three workspaces using synthetic data, with no provider calls
or JavaScript exceptions. See the [shared loading behavior](spec/frontend/workspace_shell.md#assets-and-verification).

## Formation-inclusive runtime comparison - 2026-11-03

Compare Runs now measures each question's allocated conversation memory formation
time plus retrieval and answering, excluding judging. The visible runtime
breakdown shows total formation and combined run time, per-question components,
and measurement coverage. Allocation is fixed before question-type filtering;
recorded rebuilds count once by ingestion ID. Original timing fields and source
reports remain unchanged, with new metrics in comparison schema version 2.

New query timing preserves failed attempts across resumes and checkpoints query
work before judging. Reusing a prediction adds no query time. Missing historical
measurements remain unavailable. Fifteen of the sixteen current saved reports
provide complete per-question coverage; the legacy full-context report lacks
the required timing fields. Verification: all 201 offline tests passed, including
13 focused runtime tests and the Compare Runs UI regressions. No paid provider
calls were made. See the [runtime contract](spec/frontend/compare_runs.md#metric-meaning-and-coverage).

## Approved audit follow-up - 2026-11-03

Reviewed commit `6679238` independently: the existing 165-test offline suite
passed, and saved results reproduced 30 versus 47 successes, 18 gains, one
regression, one unresolved judgment, and a 35-question priority review union.
The periodic-memory, shared-reranking, recent-first packing, and provenance work
is committed at that revision. The earlier local/uncommitted descriptions below
refer to their pre-commit implementation stages.

Added standard-library offline adjudication tooling with deterministic blinded
packets, a private condition/judge key, source hashes, category-stratified agreement
sampling, human-label import, explicit calibration denominators, and conservative
failure attribution when legacy traces are missing. Original exports remain
unchanged. [Review instructions and schema](spec/benchmark/adjudication.md)
describe the handoff; human labels are pending.

Added focused policy/accounting regressions and prepared the
[standalone reranker confirmation contract](plans/reranker_confirmation.md).
The contract is not frozen or executed: human calibration, power/sample-size
review, frozen-state execution support, and provider spending approval remain.
No real-model effectiveness result or paid provider run is added.

Verification: **179 offline tests passed** (14 new), plus a focused 10-test rerun
after strengthening full-history dataset identity validation. Diff whitespace
checks passed. The prepared packet at `instance/audit_review/2026-11-03/` contains
42 questions / 84 responses: 35 priority questions and seven seeded agreements.
CLI import of the untouched template reports zero human labels and 84 pending
answers. Source byte hashes were unchanged; no filename/config discrepancy was
found in these two source reports. Share only `reviewer/`; retain `private/`
with the coordinator. Generated artifacts are ignored runtime files, not commits.

## Saved benchmark deletion - 2026-11-02

Added **Delete** to Test Benchmark's Saved runs entries, with a run-specific
confirmation. Deletion removes the saved result, original dataset copy, worker
log, and control/lease files to free local space. Exported Compare Runs and
downloaded JSON copies are kept. Active runs must be cancelled and stopped first;
finishing threads and held worker leases also block deletion.

Successful deletion refreshes the sidebar and clears the deleted run's open
report/selection. Failed file cleanup keeps the snapshot and listed run for
retry. The new DELETE endpoint shares the registry lock with resume/cancel/review
mutations and uses an exact file list without recursive folder deletion.

Verification: **164 offline tests passed**, including eight deletion API/storage
tests and 20 frontend-state tests. JavaScript syntax and whitespace checks passed.
Isolated desktop/phone Chrome checks at 1440px/390px exercised confirm/cancel,
active guards, actual fixture cleanup, and report reset; dialog screenshots were
visually reviewed. Only temporary synthetic runs were deleted. These changes
were subsequently committed as part of `6679238`.


## Approved implementation - 2026-11-02

These changes were initially verified locally and subsequently committed as
part of `6679238`; the earlier main-branch update below remains historical.

- Added **Windowed Summary** (`windowed_summarization`) and **Windowed Fact Store**
  (`windowed_fact_store`), preserving the existing architectures. One k controls
  both the recent window and updates from each k incoming entries. Defaults are
  10 chat exchanges / 100 benchmark speaker messages. Batches span sessions;
  benchmarks flush the remainder before memory review and QA.
- Fact batches use one extraction call with multiple changes. Current facts keep
  paired user/assistant context and batch provenance. Benchmark facts apply
  per-turn operations chronologically, retaining historical versions and validated
  speaker/source attribution. Failed extraction/embedding rolls back the batch.
- Reused the pinned reranker for all embedding-based retrieval except standalone
  Vector Store: current/historical facts, Beta/Gamma long-term stores, paired
  hybrid components, and Windowed Fact Store. Candidate pool defaults to 50 per
  store, separately configurable from final retrieval k; paired hybrids support
  component overrides. Snapshots/traces expose model identity and both score types.
- Replaced the four simultaneous bar charts with **one full-width scatter plot**.
  Independent x/y selectors offer accuracy, tokens, storage, or runtime, defaulting
  to x = tokens per question and y = accuracy. Graph text matches the surrounding
  workspace without SVG font scaling. Axis ticks use English K/M/B abbreviations
  regardless of browser locale. Colors, filters, coverage, focus/touch
  tooltips, zero/missing handling, and independent table sorting remain available.
- Updated chat/API/CLI/benchmark settings and resume compatibility. Incompatible
  earlier cosine-only runs require a new run; matching standalone reranker runs
  remain eligible. Existing result exports were not rewritten.

Verification: the full **156-test offline suite** passed on Python 3.12.10,
including 13 new memory/integration tests, comparison DOM checks, and 16 frontend
state tests. JavaScript syntax and diff whitespace checks passed. Isolated
headless Chrome at **1440px and 390px** verified the plot choices, focus tooltips,
new-mode settings, and absence of page overflow; screenshots were visually
reviewed. Browser fixtures were temporary, and model/provider calls were mocked.
Real-provider extraction and matched benchmark experiments remain unverified.

The subsequent configurable-axis/typography revision passed the affected
**15-test result suite** and expanded comparison DOM checks. Headless Chrome
at 1440px/390px checked all 16 axis combinations, matching heading/body fonts,
missing/coincident-point tooltips, and no overflow. The full 156-test result
above predates this chart-only revision.

Contracts: [periodic memory](spec/memory/periodic_window.md),
[shared reranking](spec/memory/vector_store_reranker.md), and
[Compare Runs](spec/frontend/compare_runs.md).

## Main branch update — 2026-11-02

Implemented changes were committed and pushed to `origin/main` as
`8035e9bb0026211c7dff1bc3cc2a97e1fd804b67` — **Add managed run comparisons and
unify workspace UI**. This records a main-branch update, not a tagged release or
deployment. [Progress](PROGRESS.md) records implementation history;
[specifications](spec/README.md) define current contracts;
[plans](plans/README.md) track remaining work.

### Compare Runs and result files

- New uploads save directly to `data/result/` with original filenames, including
  parentheses, spaces, Unicode, and extension case. Older nested uploads remain
  usable. Previously sanitized names require re-upload to recover their names.
- Every duplicate filename gets its own Skip / Keep both / Replace choice.
  Keep both uses the first available `(1)`, `(2)`, etc. Replacement targets are
  explicit when multiple older copies share a name.
- Existing and uploaded results share Rename and confirmed Delete actions.
  Rename keeps the parent folder and bytes and rejects name conflicts.
- **Download selected** is the only download control and saves separate JSON
  files. Browsers may request permission for multiple downloads.
- Library refresh sorts by filename. One shared chart field orders all four
  graphs; the accuracy table independently defaults to name and accepts one
  category-accuracy/completion field at a time. Direction is selectable; missing
  values stay last. Run numbers/colors remain consistent across sort changes.
- Bar tooltips show the filename, module, value, scope, and relevant coverage or
  totals; keyboard focus and mobile touch expose the same details.
- The commit includes nine additional benchmark result exports and derived
  `comparison` data for six existing reports. Original fields in those six
  reports are unchanged. These files do not establish a matched benchmark study.

### Benchmark export and shared design

- Benchmark reports offer **Export to Compare Runs**, with an editable filename,
  duplicate handling, and **Open Compare Runs** after saving. Saved jobs supply
  their full export snapshot; imported reports supply a copy of the original JSON.
- The shared enrichment path fills calculable missing token/storage fields and
  recomputes comparison metrics without model calls. Missing labels/timings are
  not inferred; source reports and normal Export JSON behavior are preserved.
- Chat, Test Benchmark, and Compare Runs use a shared sidebar template and
  navigation script. Compare adopts the workspace fonts, header, colors, cards,
  controls, dialogs, and internal scrolling. Desktop collapse and the mobile
  drawer include active navigation, dismissal, and focus handling.

### Folder boundary and local operation

Library operations accept JSON paths only inside the configured `data/result/`
root. They reject traversal, absolute/drive paths, unsafe names, symlinks, and
Windows junctions. Rename cannot move files to another folder. Mutations share a
lock and enrichment uses atomic saves. These are API folder guards, not OS-level
isolation or a multi-user authentication system.

Windows setup and damaged saved-run recovery were also documented/verified on
this date; see [local setup](spec/local_setup.md) and
[recovery](spec/benchmark/results_and_resume.md#snapshot-validation-and-damaged-file-recovery).

### Verification and outstanding work

The final double-check passed the **full 143-test offline suite** on Python
3.12.10 after the final fixes, including result/API, comparison/import DOM,
frontend-state, and recovery coverage. JavaScript syntax checks also passed.
The earlier scoped checks passed 15 result tests and 14 frontend state tests.
Headless Chrome rechecked
desktop (1440px) and phone (390px) layouts, all three sidebars, sort/tooltip/file
actions, named benchmark export, derived metrics, and separate downloads against
temporary fixtures. No user result files or provider calls were used for those
browser checks. The saved-run export was additionally exercised through the real
benchmark export endpoint using a synthetic job; both saved and imported sources
remained unchanged. An actual Windows junction test preserved an external sentinel.

The earlier **138-test full offline run** remains historical evidence; the
143-test run above supersedes the previous gap in final-tree validation. Review
also fixed malformed-Unicode filename validation, prevented duplicate suffixes
from bypassing the filename byte limit, and protected reopened rename dialogs
from queued close events. Regression assertions cover those edge cases.
Comprehensive accessibility acceptance, real-provider/model validation, human calibration, and
a matched benchmark study remain outstanding. The documentation-only
reconciliation did not rerun application tests; the later double-check did.

The [documentation review](plans/documentation_review.md) inventories every
Markdown file, updates affected guides/specs/plans, preserves archived history,
and records the link and stale-contract checks.

### Post-commit documentation recheck

Rechecked all 38 Markdown files after the push. Updated affected guides, progress,
plans, and verification sections to identify commit `8035e9b` and distinguish
the final 143-test run from earlier targeted evidence. Historical archive text
and unaffected memory/protocol contracts were retained. This follow-up changes
Markdown only; application tests were not rerun for the prose changes.
Before the push, the 10-test result-analysis suite passed again with the added
reports, and result parsing and credential-pattern checks passed.
