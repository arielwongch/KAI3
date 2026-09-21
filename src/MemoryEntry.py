from typing import Any
from dataclasses import dataclass, field

@dataclass
class MemoryEntry:
    """A single unit written to or retrieved from memory.
 
    Every module (buffer, summarizer, vector store, fact store) must
    produce/consume this shape, even though internally they store very
    different things.
    """
    text: str                       # what actually gets injected into the prompt
    metadata: dict[str, Any] = field(default_factory=dict)
