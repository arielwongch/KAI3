from MemoryEntry import MemoryEntry
from MemoryModule import MemoryModule
from SlidingWindow import SlidingWindow
from Summarization import Summarization
from VectorStore import VectorStore
from FactStore import FactStore

class MemoryFactory:
    @staticmethod
    def create_memory_module(module_type:str, **kwargs) -> MemoryModule:
        controls = {'max_items', 'max_stored_entries', 'summary_limit', 'max_summary_tokens', 'fact_history_mode'}
        supported = {
            'sliding_window': {'max_items', 'max_stored_entries'},
            'summarization': {'summary_limit', 'max_summary_tokens'},
            'vector_store': {'max_stored_entries'},
            'fact_store': {'max_stored_entries', 'fact_history_mode'},
        }.get(module_type, set())
        unsupported = (controls & kwargs.keys()) - supported
        if unsupported:
            raise ValueError(f'{sorted(unsupported)[0]} does not apply to {module_type}')
        if 'max_items' in kwargs and 'max_stored_entries' in kwargs and kwargs['max_items'] != kwargs['max_stored_entries']:
            raise ValueError('Conflicting sliding-window capacities')
        if 'fact_history_mode' in kwargs and kwargs['fact_history_mode'] not in ('current', 'versioned'):
            raise ValueError('Unknown fact history mode')
        if module_type == "sliding_window":
            max_items = kwargs.get("max_stored_entries", kwargs.get("max_items", 10))
            if not isinstance(max_items, int) or max_items < 1:
                raise ValueError("max_items must be a positive integer")
            return SlidingWindow(max_items=max_items)
        elif module_type == "summarization":
            summary_limit = kwargs.get("summary_limit", 10000)
            if not isinstance(summary_limit, int) or summary_limit < 1:
                raise ValueError("summary_limit must be a positive integer")
            return Summarization(summary_limit=summary_limit, max_summary_tokens=kwargs.get('max_summary_tokens'), tokenizer=kwargs.get('tokenizer'))
        elif module_type == "vector_store":
            return VectorStore(embedder=kwargs.get("embedder"), max_stored_entries=kwargs.get('max_stored_entries'))
        elif module_type == "fact_store":
            if kwargs.get('fact_history_mode') == 'versioned':
                from TemporalFactStore import TemporalFactStore
                return TemporalFactStore(embedder=kwargs.get('embedder'), extractor=kwargs.get('extractor'), max_stored_entries=kwargs.get('max_stored_entries'))
            return FactStore(embedder=kwargs.get("embedder"), extractor=kwargs.get("extractor"), max_stored_entries=kwargs.get('max_stored_entries'))
        else:
            raise ValueError(f"Unknown memory module type: {module_type}")
