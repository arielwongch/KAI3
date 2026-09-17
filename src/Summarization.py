import MemoryModule
from collections import deque

class Summarization(MemoryModule):
    def __init__(self, k=10):
        super().__init__()
        self.memory = deque(maxlen=k)
    
    def generate_summary(self, new_entry):


        
        