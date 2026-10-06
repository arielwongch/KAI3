from API import call_api
from Diagnostics import record_memory_call
from MemoryEntry import MemoryEntry
from MemoryModule import MemoryModule

SUMMARY_PROMPT = (
    "You maintain a concise rolling summary of a conversation. "
    "Update the previous summary using the new interaction(s) in order. "
    "Preserve important facts, decisions, preferences, speaker names, dates, and context. "
    "Return only the updated summary."
)

class Summarization(MemoryModule):
    def __init__(self, summary_limit: int = 10000, max_summary_tokens=None, tokenizer=None):
        if summary_limit < 1:
            raise ValueError("summary_limit must be greater than zero")

        super().__init__()
        self.summary_limit = summary_limit
        self.summary = ""
        self.max_summary_tokens = max_summary_tokens
        self.tokenizer = tokenizer
        self.truncated = False
        if max_summary_tokens is not None:
            from MemoryContext import positive_count
            positive_count(max_summary_tokens, 'max_summary_tokens')
            if tokenizer is None:
                raise ValueError('Token-limited summaries require a tokenizer')

    def write(self, entry: MemoryEntry) -> None:
        self.generate_summary(entry)

    def generate_summary(self, new_entry: MemoryEntry) -> str:
        system_prompt = SUMMARY_PROMPT
        if self.max_summary_tokens is None:
            system_prompt += f' Keep the updated summary within {self.summary_limit} characters.'
        user_input = (
            f"Previous summary:\n{self.summary or '(none)'}\n\n"
            f"New interaction:\n{new_entry.text}"
        )
        if self.max_summary_tokens is not None:
            system_prompt += f' Keep the summary within {self.max_summary_tokens} benchmark tokens. Preserve named speakers and dates.'

        try:
            new_summary, _, tokens = call_api(system_prompt, user_input)
        except Exception:
            record_memory_call(None)
            raise
        record_memory_call(tokens)
        if not isinstance(new_summary, str):
            raise TypeError("call_api must return summary text")

        if self.max_summary_tokens is not None:
            from MemoryContext import truncate_summary
            self.summary, self.truncated = truncate_summary(new_summary, self.max_summary_tokens, self.tokenizer)
        else:
            self.summary = new_summary[:self.summary_limit]
        return self.summary

    def retrieve(self, query: str = "", k: int = 1) -> list[MemoryEntry]:
        if not self.summary:
            return []

        if k < 1:
            raise ValueError("k must be greater than zero")

        return [MemoryEntry(
            text=self.summary,
            metadata={"type": "summary", "truncated": self.truncated}
        )]

    def inspect(self):
        config = {'max_summary_tokens': self.max_summary_tokens} if self.max_summary_tokens is not None else {'summary_limit': self.summary_limit}
        config['summary_truncated'] = self.truncated
        return {"config": config, "entries": [{"text": self.summary, "metadata": {"type": "summary", "truncated": self.truncated}}] if self.summary else []}

    def iter_context_candidates(self, query, k=None):
        if k is not None:
            raise ValueError('Summarization does not support retrieval_k')
        return iter(self.retrieve(query))
