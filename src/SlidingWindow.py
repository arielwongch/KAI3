import MemoryModule
from collections import deque

class SlidingWindow(MemoryModule):
    def __init__(self, n = 10):
        self.context_window = deque(maxlen=n)

    def retrieve(self, query, k):
        pass