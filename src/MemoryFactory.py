from MemoryModule import MemoryModule
from MemoryConfig import HYBRIDS, COMPACTION_OPTION_KEYS

class MemoryFactory:
    @staticmethod
    def create_memory_module(module_type: str, **kwargs) -> MemoryModule:
        if module_type == 'compaction':
            from Compaction import Compaction, OPTION_KEYS
            allowed = {*OPTION_KEYS, 'tokenizer', 'compressor', 'memory_context_tokens', 'extractor', 'embedder'}
            if kwargs.keys() - allowed:
                raise ValueError('Unsupported compaction option: ' + sorted(kwargs.keys() - allowed)[0])
            return Compaction(**{k: v for k, v in kwargs.items() if k not in ('extractor', 'embedder')})
        if kwargs.keys() & set(COMPACTION_OPTION_KEYS):
            raise ValueError('Compaction controls only apply to compaction.')
        if module_type == 'no_memory':
            from NoMemory import NoMemory
            return NoMemory()

        if module_type in ('alpha', 'beta', 'gamma', 'windowed_summarization', 'windowed_fact_store'):
            from WindowHybridMemory import Alpha, Beta, Gamma, WindowedSummarization, WindowedFactStore
            allowed = {'max_items', 'tokenizer', 'embedder', 'extractor'}
            allowed |= {'summary_limit', 'max_summary_tokens'} if module_type in ('alpha', 'windowed_summarization') else {'max_stored_entries', 'candidate_k', 'reranker'}
            if module_type in ('gamma', 'windowed_fact_store'):
                allowed.add('fact_history_mode')
            unsupported = kwargs.keys() - allowed
            if unsupported:
                raise ValueError(f'{sorted(unsupported)[0]} does not apply to {module_type}')
            if kwargs.get('fact_history_mode', 'current') not in ('current', 'versioned'):
                raise ValueError('Unknown fact history mode')
            common = dict(max_items=kwargs.get('max_items', 10))
            if module_type in ('alpha', 'windowed_summarization'):
                summary_class = Alpha if module_type == 'alpha' else WindowedSummarization
                return summary_class(**common, summary_limit=kwargs.get('summary_limit', 10000),
                             max_summary_tokens=kwargs.get('max_summary_tokens'), tokenizer=kwargs.get('tokenizer'))
            common.update(embedder=kwargs.get('embedder'), max_stored_entries=kwargs.get('max_stored_entries'),
                          candidate_k=kwargs.get('candidate_k', 50), reranker=kwargs.get('reranker'))
            if module_type == 'beta':
                return Beta(**common)
            fact_class = Gamma if module_type == 'gamma' else WindowedFactStore
            return fact_class(**common, extractor=kwargs.get('extractor'), fact_history_mode=kwargs.get('fact_history_mode', 'current'))
        if module_type in HYBRIDS:
            from HybridMemory import HybridMemory, hybrid_settings
            names = HYBRIDS[module_type]
            allowed = {'hybrid_shares', 'component_options', 'memory_context_tokens', 'retrieval_k',
                       'max_stored_entries', 'embedder', 'tokenizer', 'extractor', 'candidate_k', 'reranker'}
            if 'summarization' in names:
                allowed |= {'summary_limit', 'max_summary_tokens'}
            if 'fact_store' in names:
                allowed.add('fact_history_mode')
            unsupported = kwargs.keys() - allowed
            if unsupported:
                raise ValueError(f'{sorted(unsupported)[0]} does not apply to {module_type}')
            shares, options = hybrid_settings(module_type, kwargs.get('hybrid_shares'), kwargs.get('component_options'))
            components = {}
            for name in names:
                if name == 'summarization':
                    child_options = {key: kwargs[key] for key in ('summary_limit', 'max_summary_tokens', 'tokenizer') if key in kwargs}
                else:
                    child_options = {key: kwargs[key] for key in ('embedder', 'max_stored_entries', 'candidate_k', 'reranker') if key in kwargs}
                    child_options.update({key: value for key, value in options.get(name, {}).items()
                                          if key in ('max_stored_entries', 'candidate_k')})
                    if 'retrieval_k' in kwargs:
                        options.setdefault(name, {}).setdefault('retrieval_k', kwargs['retrieval_k'])
                    if name == 'fact_store':
                        child_options.update({key: kwargs[key] for key in ('extractor', 'fact_history_mode') if key in kwargs})
                child_type = 'vector_store_reranker' if name == 'vector_store' else name
                components[name] = MemoryFactory.create_memory_module(child_type, **child_options)
            return HybridMemory(module_type, components, shares, options,
                                kwargs.get('memory_context_tokens', 8000), kwargs.get('tokenizer'))
        controls = {'max_items', 'max_stored_entries', 'summary_limit', 'max_summary_tokens', 'fact_history_mode',
                    'hybrid_shares', 'component_options', 'memory_context_tokens', 'retrieval_k', 'candidate_k', 'reranker'}
        supported = {
            'sliding_window': {'max_items', 'max_stored_entries'},
            'summarization': {'summary_limit', 'max_summary_tokens'},
            'vector_store': {'max_stored_entries'},
            'vector_store_reranker': {'max_stored_entries', 'candidate_k', 'reranker'},
            'fact_store': {'max_stored_entries', 'fact_history_mode', 'candidate_k', 'reranker'},
        }.get(module_type, set())
        unsupported = (controls & kwargs.keys()) - supported
        if unsupported:
            raise ValueError(f'{sorted(unsupported)[0]} does not apply to {module_type}')
        if 'max_items' in kwargs and 'max_stored_entries' in kwargs and kwargs['max_items'] != kwargs['max_stored_entries']:
            raise ValueError('Conflicting sliding-window capacities')
        if 'fact_history_mode' in kwargs and kwargs['fact_history_mode'] not in ('current', 'versioned'):
            raise ValueError('Unknown fact history mode')
        if module_type == "sliding_window":
            from SlidingWindow import SlidingWindow
            max_items = kwargs.get("max_stored_entries", kwargs.get("max_items", 10))
            if type(max_items) is not int or max_items < 1:
                raise ValueError("max_items must be a positive integer")
            return SlidingWindow(max_items=max_items)
        elif module_type == "summarization":
            from Summarization import Summarization
            summary_limit = kwargs.get("summary_limit", 10000)
            if type(summary_limit) is not int or summary_limit < 1:
                raise ValueError("summary_limit must be a positive integer")
            return Summarization(summary_limit=summary_limit, max_summary_tokens=kwargs.get('max_summary_tokens'), tokenizer=kwargs.get('tokenizer'))
        elif module_type == "vector_store":
            from VectorStore import VectorStore
            return VectorStore(embedder=kwargs.get("embedder"), max_stored_entries=kwargs.get('max_stored_entries'))
        elif module_type == "vector_store_reranker":
            from VectorStoreReranker import VectorStoreReranker
            return VectorStoreReranker(embedder=kwargs.get('embedder'), reranker=kwargs.get('reranker'),
                                       max_stored_entries=kwargs.get('max_stored_entries'), candidate_k=kwargs.get('candidate_k', 50))
        elif module_type == "fact_store":
            from FactStore import FactStore
            fact_class = FactStore
            if kwargs.get('fact_history_mode') == 'versioned':
                from TemporalFactStore import TemporalFactStore
                fact_class = TemporalFactStore
            return fact_class(embedder=kwargs.get('embedder'), extractor=kwargs.get('extractor'),
                              max_stored_entries=kwargs.get('max_stored_entries'),
                              candidate_k=kwargs.get('candidate_k', 50), reranker=kwargs.get('reranker'))
        else:
            raise ValueError(f"Unknown memory module type: {module_type}")
