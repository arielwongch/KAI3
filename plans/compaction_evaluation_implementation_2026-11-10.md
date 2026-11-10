# Compaction evaluation implementation

Implements the three priorities authorized after the paper audit: comparable
aggregate metrics, separate semantic-fidelity annotations, and paired campaign
statistics. Preserve existing results and uncommitted work. No provider calls.

1. Derive versioned compression summaries in `ResultAnalysis`: deduplicated
   committed events, sum-before/sum-after factor and weighted retained percentage,
   per-depth/per-conversation cohorts, latency percentiles, failure/no-op/unknown
   coverage. Whole-history interpretation is limited to complete one-shot cohorts;
   repeated event ratios describe operations, never original-fact retention.
2. Add offline fidelity prepare/score/calibrate functions and a CLI. User-authored
   propositions include source IDs; review targets are immutable committed outputs
   (including no-op references), bound to source/output hashes and frozen snapshot
   identity. Review labels are preserved/lost/contradicted/uncertain. Unlabelled and
   uncertain are unknown, not silently excluded or scored as lost. Output is a
   separate self-contained content-addressed evaluation artifact; it never alters
   active memory or compressor inputs. Support human labels and imported external
   judge metadata/requests, but do not invoke a semantic judge automatically.
3. Add a strict offline paired campaign comparator. Require complete recording
   archives, matching dataset/question/source/reader/judge/code/tokenizer identities
   and matching controls except explicitly declared treatment fields. Require
   matching repeat IDs, reject duplicate run/construction reuse masquerading as
   independent replicates. Primary endpoint: operational end-to-end success over
   all selected questions, with unjudged/missing counted as unsuccessful and
   coverage disclosed. Use seeded percentile bootstrap over conversations, keeping
   questions together and resampling paired repeat blocks within each sampled
   conversation. Report right-minus-left percentage points and 95% intervals;
   fewer than two independent conversations cannot yield an informative interval.
4. Expose aggregate metrics in Compare Runs and document CLI workflows, annotation
   provenance/calibration, cohort assumptions and limits. New output paths must
   be created exclusively; no overwrites or mutations of input reports.

Acceptance: unequal-source-size ratio example; repeated/no-op/failed/duplicate and
missing counter handling; exact target binding and corruption checks; incomplete
fidelity labels and human/external provenance; annotation calibration; paired
identity/repeat/source mismatches; duplicate construction rejection; reproducible
cluster bootstrap and insufficient-cluster handling; CLI no-overwrite and
portability; unchanged legacy analysis and affected frontend regressions. Run full
offline CI after focused tests. Synthetic tests establish math/custody only.

## Implemented and verified

Completed locally. Added `src/CompactionAnalysis.py`, `src/CompactionFidelity.py`,
`src/CampaignAnalysis.py`, `tools/compaction_evaluate.py` and
`tests/test_compaction_evaluation.py`. Extended `ResultAnalysis.py`, Compare Runs
chart definitions/selectors and its existing UI regression test. The maintained
[workflow specification](../spec/benchmark/compaction_evaluation.md) documents
schemas, interpretation, examples, safe output publication and limitations.

The full offline suite passed **317 tests**, including the original 16 new
evaluation tests and all affected existing frontend/persistence/recording suites.
Two additional scientific edge-case tests were subsequently added; the expanded
focused suite passed **18 tests**, including source-window exclusion and keeping
20 correlated questions per conversation together in the bootstrap. Application
code did not change after the successful full-suite run. `git diff --check`,
`node --check src/compare.js`, `node --check src/workspace.js`, and CLI help passed.
Full output: ignored `instance/compaction-evaluation-regressions.log`.

The initial test-write attempt was blocked by approval-service usage limits;
the user's retry succeeded and all intended files/tests were completed. Existing
uncommitted work and stored results were preserved. No provider experiments,
commits or pushes were performed. Human/source verification or imported model
annotations remain necessary for actual fidelity values; the workflow does not
invent semantic labels, remote compute measurements or unsupported decoding
controls. Statistical intervals have the cohort/independence limits documented
in the specification and do not prove model quality.
