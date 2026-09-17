from typing import Any
from dataclasses import dataclass, field

class MemoryEntry:
    """A single unit written to or retrieved from memory.
 
    Every module (buffer, summarizer, vector store, fact store) must
    produce/consume this shape, even though internally they store very
    different things.
    """
    text: str                       # what actually gets injected into the prompt
    session_id: str
    turn_id: int
    role: str = "user"              # "user" | "assistant" | "fact" | "summary"
    metadata: dict[str, Any] = field(default_factory=dict)
