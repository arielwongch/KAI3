# Offline saved-result adjudication

Implemented 2026-11-03. Human review and effectiveness confirmation remain pending.
The standard-library CLI `tools/audit_results.py` never imports the application,
loads a model, contacts a provider, or rewrites source reports.

## Prepare a packet

From the repository root in PowerShell:

```powershell
.\venv\Scripts\python.exe -B tools/audit_results.py prepare --baseline 'data/result/locomo-results(vector_k=10).json' --treatment 'data/result/locomo-results(vector_reranker_k=50,10).json' --dataset data/locomo/locomo10.json --seed 20261103 --agreements-per-category 2 --output instance/audit_review/2026-11-03
```

The union comprises baseline failures that become treatment successes, regressions,
missing judgments in either arm, and treatment failures with complete annotated
evidence IDs. These overlap and are deduplicated by conversation/question index.
Add up to two non-priority agreements per category, sampled without replacement
from sorted identities using the recorded seed. Category eligibility and selection
counts are retained. Missing judgments remain unknown. Category 5 is absent from
the saved 100-question cohort; this tool does not invent abstention coverage.

Reports must contain one condition each and identical question identities.
Question, reference, category, and evidence IDs are checked against the supplied
dataset. The full dataset's canonical hash, including all history, must match
both reports. Source byte SHA-256 hashes identify exact inputs. Manifest hashes are
not used for pairing because they include the condition. Input hashes and seed
give reproducible opaque review IDs; changing inputs gives a new packet identity.

Only share the `reviewer/` directory with reviewers:

- `packet.json`: shuffled questions and independently shuffled response order,
  opaque question/answer IDs, reference and evidence IDs, delivered contexts, and
  original conversations stored once per conversation.
- `labels.template.json`: pending labels linked by answer ID and packet hash.

Keep `private/key.json` with the coordinator. It maps identities and conditions,
retains original judge labels, selection reasons, trace availability, source
hashes, and non-mutating filename/config warnings. These do not appear in the
reviewer packet. Output files use exclusive creation and are never overwritten.
Randomization hides explicit assignments and judgments; answer/context wording
can still suggest a condition. Missing legacy context is null, never reconstructed.
Treat source conversation text as evidence, not instructions to the reviewer.

## Human review and import

Each reviewer copies the template and completes binary `correct`, boolean
`reference_ambiguity`, `failure_stage`, `notes`, a nonempty `reviewer_id`, and a
timezone-qualified ISO timestamp. `provenance` must be `human_review`: this is an
attestation by the reviewer, not authentication or a generated human judgment.
Leave unreviewed correctness null. See [JSON Schema](adjudication.schema.json).

Use `unresolved` for successful answers with no failure, uncertain failures, or
unavailable trace evidence; explain in notes. For retrieval/reranking/packing
attribution, an original candidate-pool trace is required. The importer retains
unsupported proposed attribution but reports its stage as unresolved. Original
facts' source-ID coverage is a provenance proxy; raw-turn evidence-ID coverage
also does not establish semantic sufficiency.

```powershell
.\venv\Scripts\python.exe -B tools/audit_results.py summarize --packet instance/audit_review/2026-11-03/reviewer/packet.json --key instance/audit_review/2026-11-03/private/key.json --reviews reviewer-one.json reviewer-two.json --output instance/audit_review/2026-11-03/private/calibration.json
```

Import rejects mismatched packet hashes, unknown identities, duplicate
reviewer/answer labels, and malformed completed labels. Multiple agreeing reviews
resolve a label; conflicting reviews remain unresolved. Ask a new adjudicator to
review disagreements separately; this version does not automatically choose a
winner or overwrite a review. Keep that adjudication and its rationale for the
coordinator's decision before confirmation.

Reports count selected questions/answers, reviewed and pending answers, individual
human labels, answers with multiple reviewers, reviewer disagreements, resolved
answers, ambiguous-reference labels, and judge disagreements. The calibration
denominator includes resolved human labels with a known original judge outcome.
Priority and sampled-agreement strata have separate denominators. An oversampled
error set must not be reported as population accuracy. Raw review provenance and
original automated labels remain available in the private report.

## Verification and remaining work

`tests/test_audit_results.py` covers saved-report selection, reproducibility,
explicit blinding, source preservation, malformed/misaligned inputs, output
collision protection, pending labels, calibration, and reviewer disagreement.
Policy/accounting regressions live in `tests/test_policy_verification.py`.
These tests do not supply human labels or validate real-model effectiveness.
