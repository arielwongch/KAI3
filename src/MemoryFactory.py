from MemoryEntry import MemoryEntry
from MemoryModule import MemoryModule
from SlidingWindow import SlidingWindow
from Summarization import Summarization

class MemoryFactory:
    @staticmethod
    def create_memory_module(module_type:str, **kwargs) -> MemoryModule:
        if module_type == "sliding_window":
            max_items = kwargs.get("max_items", 10)
            if not isinstance(max_items, int) or max_items < 1:
                raise ValueError("max_items must be a positive integer")
            return SlidingWindow(max_items=max_items)
        elif module_type == "summarization":
            summary_limit = kwargs.get("summary_limit", 10000)
            if not isinstance(summary_limit, int) or summary_limit < 1:
                raise ValueError("summary_limit must be a positive integer")
            return Summarization(summary_limit=summary_limit)
        else:
            raise ValueError(f"Unknown memory module type: {module_type}")
