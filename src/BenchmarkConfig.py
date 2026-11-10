"""Dependency-light metadata used by pages, history, and benchmark execution."""
from MemoryConfig import MODULES, RERANKED_MODULES, HYBRIDS

BENCHMARK_MODULES = MODULES[:-1] + ['question_only', 'full_context']
PROTOCOL_VERSION = 'locomo-controlled-v3'
MODULE_CAPABILITIES = {
    name: dict(records=name in ('sliding_window', 'vector_store', 'vector_store_reranker', 'fact_store') or name in (*HYBRIDS, 'beta', 'gamma', 'windowed_fact_store'),
               reranker=name in RERANKED_MODULES,
               summary=name == 'summarization' or name in ('delta', 'epsilon', 'alpha', 'windowed_summarization'),
               facts=name in ('fact_store', 'epsilon', 'zeta', 'gamma', 'windowed_fact_store'),
               hybrid=name in HYBRIDS, components=list(HYBRIDS.get(name, ())), memory=name in MODULES[:-1])
    for name in BENCHMARK_MODULES
}
