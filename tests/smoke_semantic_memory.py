"""Opt-in real-model check: python tests/smoke_semantic_memory.py.

Downloads MiniLM on first use. Fact extraction remains mocked; no API calls.
"""

import json
import os
from pathlib import Path
import sys

os.environ.setdefault("DEEPSEEK_API_KEY", "smoke-test-unused")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from Embeddings import LocalEmbeddings, _load_model
from FactStore import FactStore
from MemoryEntry import MemoryEntry
from VectorStore import VectorStore


def main():
    embeddings = LocalEmbeddings()
    memory = VectorStore(embeddings)
    memory.write(MemoryEntry("I follow a vegetarian diet and never eat meat."))
    memory.write(MemoryEntry("My favorite pastime is reading science fiction novels."))
    result = memory.retrieve("What kinds of books do I enjoy?", 1)
    assert "science fiction" in result[0].text, result

    long_text = "Today's weather is cloudy with mild temperatures. " * 100
    long_text += "The deployment access code is sapphire."
    chunks = embeddings.chunks(long_text)
    model = _load_model()
    assert len(chunks) > 1
    assert all(len(model.tokenizer.encode(chunk)) <= model.max_seq_length for chunk in chunks)
    memory = VectorStore(embeddings)
    memory.write(MemoryEntry(long_text, {"source": "long interaction"}))
    memory.write(MemoryEntry("The dinner reservation is at seven o'clock."))
    result = memory.retrieve("What is the password for deployment?", 1)
    assert result[0].metadata["source"] == "long interaction", result

    def extractor(system_prompt, user_input):
        return json.dumps({"operations": [
            {"op": "add", "text": "The user enjoys science fiction novels."},
            {"op": "add", "text": "The user follows a vegetarian diet."},
        ]}), 0., 0

    facts = FactStore(embeddings, extractor)
    facts.write(MemoryEntry("I enjoy science fiction and follow a vegetarian diet."))
    assert "vegetarian" in facts.retrieve("What food should I avoid serving?", 1)[0].text
    print(f"PASS: paraphrase retrieval, long interaction ({len(chunks)} chunks), and semantic fact retrieval")


if __name__ == "__main__":
    main()
