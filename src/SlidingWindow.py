import MemoryModule
from MemoryEntry import MemoryEntry
from collections import deque

class SlidingWindow(MemoryModule):
    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns
        self.buffer = list()

    def write(self, entry: MemoryEntry) -> None:
        self.buffer.append(entry)
        if len(self.buffer) > self.max_turns:
            self.buffer.pop(0)

    def retrieve(self, query: str, k: int = 5) -> list[MemoryEntry]:
        # sliding-window ignores the query entirely — it just returns recent turns
        return self.buffer[-k:]