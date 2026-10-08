# Sliding window memory

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

Implementation: [SlidingWindow.py](../../src/SlidingWindow.py).

## Purpose

The window uses recency as the selection rule; query meaning has no effect.

## Stored data and write flow

Append each formatted turn to `deque(maxlen=N)`, preserving
its metadata. At capacity, the next write discards the oldest turn and increments
`evicted_count`. N defaults to 10. A record is one dialogue turn, not a session or
a user/assistant pair. There are no embeddings or memory LLM calls.

## Retrieval

Benchmark candidates are detached copies, newest first. Apply k
to that ordering, then pack whole turns. Render selected turns oldest first so
the answer model sees their conversational order. The live-chat `retrieve`
method instead returns the latest k entries already in chronological order.

## Example

After ingesting T1 through T12 with capacity 10, retain T3 through
T12. With k=5, consider T12 through T8. If all fit, supply T8 through T12. With
k=null, all ten retained turns are eligible; a long recent turn can be skipped
while an older, smaller eligible turn fits.

## Limitations

Evicted evidence is unavailable even when semantically relevant. Blank
queries still return recent candidates. Original `dialogue_id` metadata supports
evidence coverage. The benchmark's candidate copies are detached, but `write`
stores the passed entry object and live-chat `retrieve` exposes stored entries;
direct callers should not mutate them.

## Interfaces and configuration

`MemoryFactory.create_memory_module("sliding_window", max_stored_entries=10)`
constructs a `SlidingWindow(max_items=10)`. The legacy `max_items` alias is
accepted; conflicting capacities are rejected. Capacity is a positive integer.
Benchmark candidate k is a positive integer or null; live retrieval defaults to 5.

The [shared interface](interface.md) defines module calls and snapshots.
The benchmark applies [context packing](../benchmark/context_budget.md) after
candidate selection; storage and retrieval limits are independent.

## Failure behavior

Invalid capacity or benchmark candidate k raises `ValueError`. The deque
write has no model dependency. Live `retrieve` uses Python slicing and does
not perform the strict benchmark k validation.

## Verification

[Controlled comparison tests](../../tests/test_controlled_comparison.py) cover
capacity, eviction, k, chronological rendering, and the shared token allowance.
