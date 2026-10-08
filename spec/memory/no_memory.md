# No-memory component

Status: implemented behavior. Last checked against repository source: 2026-10-08.
This check date is not an implementation or release date.

## Purpose and interfaces

`NoMemory` satisfies the [shared interface](interface.md) without retaining
conversation entries. Live chat uses mode `no_memory`; benchmark
[reference baselines](../benchmark/baselines.md) reuse this component but supply
different context through the runner.

## Stored data and write flow

There are no records or embeddings. `write(entry)` is a no-op. No memory LLM
calls, capacity management, or persistence occur.

## Retrieval and inspection

`retrieve(query, k=5)` always returns `[]`; `iter_context_candidates(query, k=None)`
returns an empty iterator. Both ignore query and k. `inspect()` returns
`{"config": {"architecture": "no_memory"}, "entries": []}`.

## Configuration, failures, and limitations

Construct with `NoMemory()`. There are no storage/retrieval controls or memory
failure paths involving external dependencies. The benchmark validates baseline
settings outside the component. NoMemory itself does not build the full-context
transcript: the benchmark runner owns that string. Empty memory does not mean
the answer request has no instructions, question, or provider token usage.

## Source and verification

[NoMemory.py](../../src/NoMemory.py) implements the component.
[Integration tests](../../tests/test_memory_integration.py) and
[controlled comparison tests](../../tests/test_controlled_comparison.py) cover
no-memory integration and explicit baseline selection.
