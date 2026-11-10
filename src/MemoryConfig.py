"""Shared architecture choices and surface-specific window settings."""
HYBRIDS = {
    'delta': ('summarization', 'vector_store'),
    'epsilon': ('summarization', 'fact_store'),
    'zeta': ('vector_store', 'fact_store'),
}
COMPACTION_OPTION_KEYS = ('retain_percent', 'compaction_mode', 'compaction_trigger_tokens',
                          'compaction_source_entries')
MODULES = ['sliding_window', 'summarization', 'vector_store', 'vector_store_reranker',
           'fact_store', 'windowed_summarization', 'windowed_fact_store', 'delta', 'epsilon', 'zeta', 'alpha', 'beta', 'gamma', 'compaction', 'no_memory']
PERIODIC_MODULES = ('windowed_summarization', 'windowed_fact_store')
HYBRID_MODULES = ('alpha', 'beta', 'gamma', *PERIODIC_MODULES)
RERANKED_MODULES = ('vector_store_reranker', 'fact_store', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'windowed_fact_store')
WINDOW_MODULES = ('sliding_window', *HYBRID_MODULES)


def window_size_for(mode, options, default):
    if 'window_size' in options:
        if mode not in WINDOW_MODULES:
            raise ValueError('Window size is only supported by window-based architectures.')
        value = options['window_size']
        if type(value) is not int or value < 1:
            raise ValueError('Window size must be a positive integer.')
        return value
    return default if mode in WINDOW_MODULES else None


def retrieval_policy(mode, window_size=None):
    if mode == 'compaction':
        return dict(strategy='complete_active_compaction_state', secondary_packing=False)
    if mode in HYBRID_MODULES:
        return dict(strategy='window_plus_summary' if mode in ('alpha', 'windowed_summarization') else 'window_plus_recall',
                    window_size=window_size, long_term_k=1 if mode in ('alpha', 'windowed_summarization') else 5)
    if mode in ('delta', 'epsilon', 'zeta'):
        return dict(strategy='independent_components', components=list(HYBRIDS[mode]), k=5)
    if mode in RERANKED_MODULES:
        return dict(strategy='vector_shortlist_rerank', k=5)
    if mode == 'sliding_window':
        return dict(strategy='full_window', window_size=window_size)
    if mode == 'no_memory':
        return dict(strategy='none')
    return dict(strategy='summary' if mode == 'summarization' else 'semantic',
                k=1 if mode == 'summarization' else 5)
