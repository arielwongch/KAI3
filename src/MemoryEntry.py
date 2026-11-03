from typing import Any
from dataclasses import dataclass, field

@dataclass
class MemoryEntry:
    """Shared memory record; text supplies prompt context and metadata tracks provenance."""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
