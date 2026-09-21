from abc import ABC, abstractmethod
from MemoryEntry import MemoryEntry

class MemoryModule(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def retrieve(query: str, k: int) -> list[MemoryEntry]:
        pass

    @abstractmethod
    def write(entry: MemoryEntry) -> None:
        pass
