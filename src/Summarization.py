from API import call_api
from MemoryEntry import MemoryEntry
from MemoryModule import MemoryModule

class Summarization(MemoryModule):
    def __init__(self, summary_limit: int = 10000):
        if summary_limit < 1:
            raise ValueError("summary_limit must be greater than zero")

        super().__init__()
        self.summary_limit = summary_limit
        self.summary = ""

    def write(self, entry: MemoryEntry) -> None:
        self.generate_summary(entry)

    def generate_summary(self, new_entry: MemoryEntry) -> str:
        system_prompt = (
            "You maintain a concise rolling summary of a conversation. "
            "Update the previous summary using the new interaction. "
            "Preserve important facts, decisions, preferences, and context. "
            "Return only the updated summary."
        )
        user_input = (
            f"Previous summary:\n{self.summary or '(none)'}\n\n"
            f"New interaction:\n{new_entry.text}"
        )

        new_summary, _, _ = call_api(system_prompt, user_input)
        if not isinstance(new_summary, str):
            raise TypeError("call_api must return summary text")

        self.summary = new_summary[:self.summary_limit]
        return self.summary

    def retrieve(self, query: str = "", k: int = 1) -> list[MemoryEntry]:
        if not self.summary:
            return []

        if k < 1:
            raise ValueError("k must be greater than zero")

        return [MemoryEntry(
            text=self.summary,
            metadata={"type": "summary"}
        )]