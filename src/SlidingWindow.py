from dataclasses import asdict
from copy import deepcopy
from Embeddings import MODEL_NAME
from collections import deque
from MemoryModule import MemoryModule
from MemoryEntry import MemoryEntry

class SlidingWindow(MemoryModule):
    context_order = 'chronological'
    def __init__(self, max_items: int = 10):
        from MemoryContext import positive_count
        positive_count(max_items, 'max_items')
        self.buffer = deque(maxlen=max_items)
        self.evicted_count = 0

    def write(self, entry: MemoryEntry) -> None:
        if len(self.buffer) == self.buffer.maxlen:
            self.evicted_count += 1
        self.buffer.append(entry)

    def iter_context_candidates(self, query, k=None):
        from MemoryContext import positive_count
        positive_count(k, 'retrieval_k', unlimited=True)
        entries = list(reversed(self.buffer))
        return iter(deepcopy(entries if k is None else entries[:k]))

    def retrieve(self, query: str, k: int = 5) -> list[MemoryEntry]:
        # sliding-window ignores the query entirely, it just returns recent turns
        return list(self.buffer)[-k:]

    def inspect(self):
        return {"config": {"max_items": self.buffer.maxlen, "evicted_count": self.evicted_count}, "entries": [asdict(deepcopy(e)) for e in self.buffer]}
