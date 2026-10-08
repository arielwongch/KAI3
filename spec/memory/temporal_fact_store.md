# Temporal fact memory

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

Implementation: [TemporalFactStore.py](../../src/TemporalFactStore.py), selected by
`MemoryFactory.create_memory_module("fact_store", fact_history_mode="versioned")`.
The benchmark enforces this history mode.

## Purpose

An LLM converts each turn into atomic assertions and explicit
updates. Both named participants are evidence. The store preserves changed or
withdrawn assertions as searchable historical versions with status labels.

## Stored data

The in-memory dictionary maps `version_id` to `(MemoryEntry, embedding)`.
Entry text is the extracted assertion, not the full original turn. Metadata includes:

| Field | Meaning |
| --- | --- |
| `fact_id`, `version_id` | Logical assertion chain and unique version; IDs are local to this conversation |
| `speaker`, `status` | Assertion owner; `current`, `superseded`, `corrected`, or `retracted` |
| `source_ids`, `source_observations` | Supporting dialogue IDs and session/timestamp/revision observations |
| `source`, `source_text` | Original creation-turn metadata snapshot and formatted text |
| `observed_from`, `observed_until`, `observed_revision` | When this version was observed and, if applicable, changed or withdrawn |
| `prior_version_id`, `next_version_id` | Version links when applicable; availability flags identify evicted links |
| `transition_source_ids` | Evidence for a change/withdrawal, separate from support for the old assertion |
| `valid_from`, `valid_until` | Currently null; observation timestamps do not establish real-world validity |

Asserted dates can be preserved in assertion text and source text. There is no
separate implemented operation that populates real-world validity intervals.

## Write and update flow

Ignore blank or `completed=False` entries. Other writes require string `speaker`
and `dialogue_id` metadata. Send the current formatted turn and all retained
versions to the extractor, with instructions to avoid inventing facts, dates, or
IDs and to distinguish actual change from correction. One turn may produce zero,
one, or several operations.

The response must be a JSON object containing only an `operations` array:

| Operation | Required fields besides `op` | Effect |
| --- | --- | --- |
| `add` | `text`, `source_ids`, `supporting_version_ids` | Create a current assertion version |
| `confirm` | `id`, `source_ids` | Add support to an existing current version without creating a new one |
| `supersede` | `id`, `text`, `source_ids`, `supporting_version_ids` | Mark old version superseded and create a linked current version for a real-world change |
| `correct` | `id`, `text`, `source_ids`, `supporting_version_ids` | Mark old version corrected and create a linked replacement for an erroneous claim |
| `retract` | `id`, `source_ids` | Mark old version retracted, retaining its text and embedding |

`id` targets a version ID, not a fact ID. Validate exact field sets, nonempty
assertion text, and `source_ids` equal to the one current dialogue ID. Targets
must exist, be current, belong to the same speaker, and occur at most once per
response. Supporting versions must also be existing current versions of that
speaker. All references are validated against the pre-write snapshot.

Stage the operations on a detached copy. New assertions receive the current turn's
support plus the source IDs of explicitly referenced supporting versions. A
replacement does not automatically inherit the old assertion's sources.
Confirmations merge source IDs and append observations without refreshing version
creation order. Empty operations add no support. Case/whitespace-normalized exact
duplicates among a speaker's current assertions merge support rather than create
another record; semantic paraphrase decisions depend on the extractor.

Embed new assertion texts, one vector per assertion, using the shared normalized
MiniLM embedding helper. Fact texts do not use vector-store chunking. Prepare and
validate all new embeddings before committing records, IDs, revisions, and
eviction counts. Malformed extraction or failed embeddings leave existing state
unchanged. Code validates reference integrity; whether cited text actually supports
an assertion still depends on extraction quality.

Storage is unlimited by default. A finite capacity counts every version, including
historical versions, and removes the earliest-created retained versions after
staging the transaction. Confirmation/status changes do not refresh that order.
Eviction removes the record and embedding; surviving records retain their own
provenance, and links to missing versions are marked unavailable.

## Retrieval

Embed the question and rank every retained version, including non-current ones,
by descending cosine similarity of its assertion text. Ties favor higher
`observed_revision`, then the larger numeric version ID. There is no similarity
threshold or preference for current status. Confirming a version does not update
its `observed_revision`. Empty stores and blank queries return no candidates.

Return detached entries with retrieval scores/ranks and render labels as:

```text
[Bob | session_1 | <timestamp> | superseded] Bob works at Google.
```

If the version has an end observation, append an assertion-status transition
label containing that observation's session and timestamp. Labels consume context
tokens. Apply k before whole-record packing and retain similarity order.

For example, after "I work at Google" followed by "I now work at Microsoft",
an extracted `supersede` keeps the Google assertion searchable for a question
about previous employment. An extracted `correct` instead labels the old claim
as erroneous. Historical versions are retained candidates, not guaranteed
retrieval results: ranking, k, storage eviction, and the token allowance still apply.

## Limitations

Source-ID coverage is a provenance proxy, not proof that every detail
from a source turn survived extraction. Historical records can consume context
needed by current facts. The extraction prompt grows with retained versions;
the answer-context allowance does not cap extraction input. Invalid extraction
can block QA for that conversation.

## Interfaces and configuration

Use the [shared interface](interface.md) with factory type `fact_store` and
`fact_history_mode="versioned"`. The factory accepts an injectable embedder and
extractor, plus `max_stored_entries=None` (unlimited) or a positive capacity.
Live-style `retrieve` defaults to k=5; benchmark candidate k accepts null for all.
The extractor takes `(system_prompt, payload)` and returns `(text, latency, tokens)`.
The benchmark injects `benchmark_extractor`, which adds speaker-preservation
instructions. [Current fact memory](fact_store.md) is a separate implementation.

## Failure behavior

Malformed operations, invalid targets/sources, and failed embeddings reject the
whole staged transaction. No record or revision is committed. Missing required
speaker/dialogue metadata fails before extraction. Query embedding failures
propagate. The benchmark records ingestion failure and blocks pending questions
for that conversation; it does not silently use the partial store for QA.

## Verification

[Controlled comparison tests](../../tests/test_controlled_comparison.py) cover
history, confirmation, retraction, speaker isolation, validated provenance,
atomic failures, capacity, version links, and evidence coverage.
