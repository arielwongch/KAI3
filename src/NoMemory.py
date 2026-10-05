"""Memory architecture that deliberately stores and retrieves nothing."""
from MemoryModule import MemoryModule


class NoMemory(MemoryModule):
    def retrieve(self, query, k=5):
        return []

    def write(self, entry):
        return None

    def inspect(self):
        return {"config": {"architecture": "no_memory"}, "entries": []}


# Keep the public factory contract aligned with the architectures exposed by
# the application while preserving the factory's existing implementations.
try:
    from MemoryFactory import MemoryFactory
    _factory_create_memory_module = MemoryFactory.create_memory_module

    def _create_memory_module(memory_type, **kwargs):
        if memory_type == "no_memory":
            return NoMemory()
        return _factory_create_memory_module(memory_type, **kwargs)

    MemoryFactory.create_memory_module = staticmethod(_create_memory_module)
except ImportError:
    pass
