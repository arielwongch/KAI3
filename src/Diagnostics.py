"""Context-local LLM accounting shared by chat and benchmark execution."""
from contextvars import ContextVar
from dataclasses import asdict
from copy import deepcopy

collector = ContextVar("memory_llm_metrics", default=None)
retrieval_collector = ContextVar('retrieval_metrics', default=None)
retrieval_component = ContextVar('retrieval_component', default=None)


def record_retrieval(stage, entries, **details):
    """Request-local diagnostic records; annotations never affect ranking."""
    metrics = retrieval_collector.get()
    if metrics is None:
        return
    records = []
    for entry in entries:
        m = entry.metadata
        records.append(dict(dialogue_id=m.get('dialogue_id'),
                            source_ids=deepcopy(m.get('source_ids', [])),
                            fact_id=m.get('version_id', m.get('fact_id')),
                            rank=m.get('retrieval_rank'), score=m.get('retrieval_score')))
    metrics.setdefault('retrieval_traces', []).append(dict(
        stage=stage, component=retrieval_component.get(), records=records, **details))

def record_memory_call(tokens):
    metrics = collector.get()
    if metrics is not None:
        metrics["memory_llm_calls"] += 1
        if tokens is None:
            metrics["memory_tokens"] = None
            metrics['memory_prompt_tokens'] = None
            metrics['memory_completion_tokens'] = None
        elif metrics["memory_tokens"] is not None:
            metrics["memory_tokens"] += tokens

def entries_json(entries):
    return [asdict(deepcopy(entry)) for entry in entries]

def totals(turns):
    keys = ("retrieval_seconds", "agent_seconds", "write_seconds", "total_seconds",
            "agent_llm_calls", "memory_llm_calls", "agent_tokens", "memory_tokens")
    return {key: None if any(t.get(key) is None for t in turns) else
            sum(t.get(key, 0) for t in turns) for key in keys}
