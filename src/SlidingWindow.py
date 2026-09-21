from collections import deque
from MemoryModule import MemoryModule
from MemoryEntry import MemoryEntry

class SlidingWindow(MemoryModule):
    def __init__(self, max_turns: int = 10):
        self.buffer = deque(maxlen=max_turns)

    def write(self, entry: MemoryEntry) -> None:
        self.buffer.append(entry)

    def retrieve(self, query: str, k: int = 5) -> list[MemoryEntry]:
        # sliding-window ignores the query entirely, it just returns recent turns
        return list(self.buffer)[-k:]