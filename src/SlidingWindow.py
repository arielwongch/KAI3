import MemoryModule
from MemoryEntry import MemoryEntry
from collections import deque

class SlidingWindow(MemoryModule):
    def __init__(self, max_turns: int = 10):
        self.context_window = deque(maxlen=max_turns)

    def retrieve(self, query: str) -> MemoryEntry:
        pass