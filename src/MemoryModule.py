from abc import ABC, abstractmethod

class MemoryModule(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def retrieve(self, query, k):
        pass

    @abstractmethod
    def write(self, entry):
        pass
