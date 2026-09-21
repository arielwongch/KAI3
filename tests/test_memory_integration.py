import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, "src")

import ReAct
import Summarization as summarization_module
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from Summarization import Summarization


class FakeCompletions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.calls.append(kwargs)
        response_text = self.owner.response_text
        if isinstance(response_text, list):
            response_text = response_text.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response_text))],
            usage=SimpleNamespace(total_tokens=7),
        )


class FakeOpenAIClient:
    def __init__(self, response_text="Thought: I have the final answer.\nFinal Answer: done"):
        self.response_text = response_text
        self.calls = []
        self.chat = SimpleNamespace(completions=FakeCompletions(self))


class MemoryIntegrationTests(unittest.TestCase):
    def test_sliding_window_is_injected_and_written(self):
        module = MemoryFactory.create_memory_module("sliding_window", max_items=3)
        module.write(MemoryEntry("earlier"))
        fake_client = FakeOpenAIClient()

        with patch.object(ReAct, "client", fake_client):
            ReAct.run_ReAct("new request", memory_module=module)

        prompt = fake_client.calls[0]["messages"][0]["content"]
        self.assertIn("earlier", prompt)
        entries = module.retrieve("", 5)
        self.assertEqual(len(entries), 2)
        self.assertIn("User: new request", entries[-1].text)

    def test_empty_summarization_is_valid(self):
        module = Summarization()
        self.assertEqual(module.retrieve("new request", 5), [])

    def test_summarization_is_injected_after_first_write(self):
        module = MemoryFactory.create_memory_module("summarization")
        fake_client = FakeOpenAIClient()
        summary_call = patch.object(
            summarization_module, "call_api", return_value=("remembered context", 0.0, 4)
        )

        with patch.object(ReAct, "client", fake_client), summary_call as mocked_summary:
            ReAct.run_ReAct("new request", memory_module=module)

        self.assertEqual(module.retrieve("", 1)[0].text, "remembered context")
        self.assertEqual(module.retrieve("", 5)[0].text, "remembered context")
        self.assertIn("(none)", mocked_summary.call_args.args[1])

    def test_memory_module_is_required(self):
        with self.assertRaises(ValueError):
            ReAct.run_ReAct("request")

    def test_malformed_response_is_rejected_and_retried(self):
        fake_client = FakeOpenAIClient([
            "I can help with that.",
            "Thought: I have the final answer.\nFinal Answer: done",
        ])

        with patch.object(ReAct, "client", fake_client):
            result, _, _ = ReAct.run_ReAct("request")

        self.assertIn("Task completed successfully.", result)
        self.assertEqual(len(fake_client.calls), 2)
        self.assertTrue(any(
            isinstance(message, dict)
            and "did not match the required format" in message.get("content", "")
            for message in fake_client.calls[1]["messages"]
        ))

    def test_memory_module_type_is_validated(self):
        with self.assertRaises(TypeError):
            ReAct.run_ReAct("request", memory_module=object())


if __name__ == "__main__":
    unittest.main()
