"""Memory architecture that deliberately stores and retrieves nothing."""
from MemoryModule import MemoryModule


class NoMemory(MemoryModule):
    def retrieve(self, query, k=5):
        return []

    def write(self, entry):
        return None

    def inspect(self):
        return {"config": {"architecture": "no_memory"}, "entries": []}

    def iter_context_candidates(self, query, k=None):
        return iter(())
