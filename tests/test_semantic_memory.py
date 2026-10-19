import json
import os
import sys
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("DEEPSEEK_API_KEY", "test-only")
sys.path.insert(0, "src")

from Embeddings import LocalEmbeddings, embed_checked
from FactStore import FactStore
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from VectorStore import VectorStore
import app as web
import ReAct
from test_memory_integration import FakeOpenAIClient


class FakeEmbeddings:
    def chunks(self, text):
        return text.split("|")

    def embed(self, texts):
        return [[1., 0.] if any(word in text.lower() for word in ("cat", "feline"))
                else [0., 1.] for text in texts]


def extraction(*operations):
    return (json.dumps({"operations": list(operations)}), 0., 0)


class SemanticMemoryTests(unittest.TestCase):
    def test_vector_ranking_chunks_dedup_and_copies(self):
        module = VectorStore(FakeEmbeddings())
        entry = MemoryEntry("dog|cat|cat", {"nested": {"value": 1}})
        module.write(entry)
        module.write(MemoryEntry("dog"))
        entry.metadata["nested"]["value"] = 2
        result = module.retrieve("feline", 10)
        self.assertEqual([e.text for e in result], ["dog|cat|cat", "dog"])
        self.assertEqual(result[0].metadata["nested"]["value"], 1)
        result[0].text = "changed"
        self.assertEqual(module.retrieve("feline", 1)[0].text, "dog|cat|cat")

    def test_vector_ties_and_atomic_failure(self):
        embedder = FakeEmbeddings()
        module = VectorStore(embedder)
        module.write(MemoryEntry("cat one"))
        module.write(MemoryEntry("cat two"))
        self.assertEqual(module.retrieve("cat", 1)[0].text, "cat two")
        with patch.object(embedder, "embed", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                module.write(MemoryEntry("new"))
        self.assertEqual(len(module.retrieve("cat", 10)), 2)

    def test_empty_queries_limits_and_isolation(self):
        for kind in ("vector_store", "fact_store"):
            with self.subTest(kind=kind):
                extractor = Mock(return_value=extraction({"op": "add", "text": "cat"}))
                module = MemoryFactory.create_memory_module(kind, embedder=FakeEmbeddings(), extractor=extractor)
                other = MemoryFactory.create_memory_module(kind, embedder=FakeEmbeddings(), extractor=extractor)
                self.assertEqual(module.retrieve("cat", 5), [])
                module.write(MemoryEntry("cat"))
                self.assertEqual(other.retrieve("cat", 5), [])
                self.assertEqual(module.retrieve("  ", 5), [])
                for k in (0, -1, True, 1.5):
                    with self.assertRaises(ValueError):
                        module.retrieve("cat", k)

    def test_fact_add_correct_retract_and_deduplicate(self):
        extractor = Mock(side_effect=[
            extraction({"op": "add", "text": "Likes cats"}, {"op": "add", "text": "Likes dogs"}),
            extraction({"op": "add", "text": " likes CATS "}),
            extraction(),  # A paraphrase is recognized by the extractor.
            extraction({"op": "replace", "id": "fact-1", "text": "Dislikes cats"}),
            extraction({"op": "remove", "id": "fact-2"}),
        ])
        module = FactStore(FakeEmbeddings(), extractor)
        module.write(MemoryEntry("I like cats and dogs", {"tag": "source"}))
        self.assertEqual(module.retrieve("feline", 1)[0].metadata["fact_id"], "fact-1")
        module.write(MemoryEntry("I like cats"))
        module.write(MemoryEntry("I enjoy felines"))
        self.assertEqual(len(module.retrieve("pets", 10)), 2)
        module.write(MemoryEntry("Actually I dislike cats"))
        fact = module.retrieve("cat", 1)[0]
        self.assertEqual((fact.text, fact.metadata["fact_id"]), ("Dislikes cats", "fact-1"))
        self.assertEqual(fact.metadata["source_text"], "Actually I dislike cats")
        module.write(MemoryEntry("Forget that I like dogs"))
        self.assertEqual(len(module.retrieve("pets", 10)), 1)

    def test_fact_failures_are_atomic(self):
        extractor = Mock(return_value=extraction({"op": "add", "text": "cat"}))
        embedder = FakeEmbeddings()
        module = FactStore(embedder, extractor)
        module.write(MemoryEntry("cat"))
        before = module.retrieve("cat", 5)
        invalid = ["not JSON", '[]', '{"operations":{}}',
                   extraction({"op": "add", "text": "dog"}, {"op": "remove", "id": "missing"})[0],
                   extraction({"op": "remove", "id": "fact-1"}, {"op": "remove", "id": "fact-1"})[0],
                   extraction({"op": "add", "text": " "})[0]]
        for response in invalid:
            extractor.return_value = (response, 0, 0)
            with self.assertRaises(ValueError):
                module.write(MemoryEntry("new"))
            self.assertEqual(module.retrieve("cat", 5), before)
        extractor.return_value = extraction({"op": "remove", "id": "fact-1"}, {"op": "add", "text": "dog"})
        with patch.object(embedder, "embed", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                module.write(MemoryEntry("new"))
        self.assertEqual(module.retrieve("cat", 5), before)
        extractor.side_effect = RuntimeError("provider failure")
        with self.assertRaises(RuntimeError):
            module.write(MemoryEntry("new"))
        self.assertEqual(module.retrieve("cat", 5), before)

    def test_fact_speaker_boundaries_and_incomplete_turns(self):
        extractor = Mock(return_value=extraction())
        module = FactStore(FakeEmbeddings(), extractor)
        module.write(MemoryEntry("combined", {"user_text": "Hello", "assistant_text": "You own a cat"}))
        prompt, payload = extractor.call_args.args
        self.assertIn("never extract assistant guesses", prompt)
        self.assertEqual(json.loads(payload)["user_text"], "Hello")
        self.assertEqual(module.retrieve("cat", 5), [])
        module.write(MemoryEntry("cat", {"completed": False}))
        module.write(MemoryEntry("assistant only", {"user_text": ""}))
        self.assertEqual(extractor.call_count, 1)

    def test_real_chunker_with_fake_tokenizer(self):
        tokenizer = Mock()
        tokenizer.encode.side_effect = lambda text, add_special_tokens, **kw: text.split() + (["special"] if add_special_tokens else [])
        tokenizer.decode.side_effect = lambda tokens, **kw: " ".join(tokens)
        tokenizer.num_special_tokens_to_add.return_value = 1
        model = Mock(tokenizer=tokenizer, max_seq_length=9)
        with patch("Embeddings._load_model", return_value=model):
            chunks = LocalEmbeddings().chunks(" ".join(map(str, range(20))))
        self.assertTrue(all(len(chunk.split()) <= 8 for chunk in chunks))
        self.assertEqual(chunks[0].split()[-2:], chunks[1].split()[:2])
        self.assertEqual(chunks[-1].split()[-1], "19")

    def test_embedding_validation(self):
        for vectors in ([], [[0, 0]], [[float("nan"), 1]]):
            with self.assertRaises(ValueError):
                embed_checked(Mock(embed=Mock(return_value=vectors)), ["cat"])

    def test_model_loading_is_lazy(self):
        with patch("Embeddings._load_model") as load:
            for kind in ("vector_store", "fact_store"):
                module = MemoryFactory.create_memory_module(kind)
                self.assertEqual(module.retrieve("cat", 1), [])
            load.assert_not_called()

    def test_fact_update_recency_and_returned_copy(self):
        extractor = Mock(side_effect=[
            extraction({"op": "add", "text": "cat one"}, {"op": "add", "text": "cat two"}),
            extraction({"op": "replace", "id": "fact-1", "text": "cat three"}),
        ])
        module = FactStore(FakeEmbeddings(), extractor)
        module.write(MemoryEntry("cats", {"tag": {"number": 1}}))
        self.assertEqual(module.retrieve("cat", 1)[0].text, "cat two")
        result = module.retrieve("cat", 1)[0]
        result.metadata["source"]["tag"]["number"] = 2
        self.assertEqual(module.retrieve("cat", 1)[0].metadata["source"]["tag"]["number"], 1)
        module.write(MemoryEntry("correction"))
        self.assertEqual(module.retrieve("cat", 1)[0].text, "cat three")

    def test_agent_and_flask_integration(self):
        for kind in ("vector_store", "fact_store"):
            with self.subTest(kind=kind):
                web.chat_memory_modules.clear()
                extractor = Mock(return_value=extraction({"op": "add", "text": "User likes cats"}))
                def factory(selected):
                    return MemoryFactory.create_memory_module(selected, embedder=FakeEmbeddings(), extractor=extractor)
                client = web.app.test_client()
                fake_llm = FakeOpenAIClient()
                with patch.object(web, "MemoryFactory", create_memory_module=factory), patch.object(ReAct, "client", fake_llm):
                    for message in ("I like cats", "What pets do I like?"):
                        response = client.post("/get", json={"chat_id": "one", "memory_module": kind, "message": message})
                        self.assertEqual(response.status_code, 200)
                    self.assertIn("cats", fake_llm.calls[1]["messages"][0]["content"])
                    response = client.post("/get", json={"chat_id": "two", "memory_module": kind, "message": "hello"})
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn("cats", fake_llm.calls[2]["messages"][0]["content"])
                    response = client.post("/get", json={"chat_id": "one", "memory_module": "sliding_window", "message": "hello"})
                    self.assertEqual(response.status_code, 409)
                    self.assertIn(kind, client.get("/chat").get_data(as_text=True))
                if kind == "fact_store":
                    self.assertEqual(json.loads(extractor.call_args.args[1])["user_text"], "hello")
                    self.assertEqual(json.loads(extractor.call_args.args[1])["assistant_context"], "done")
        web.chat_memory_modules.clear()

    def test_flask_failure_preserves_memory(self):
        module = FactStore(FakeEmbeddings(), Mock(return_value=extraction({"op": "add", "text": "cat"})))
        module.write(MemoryEntry("cat"))
        module.extractor.return_value = ("bad JSON", 0, 0)
        with patch.object(web.MemoryFactory, "create_memory_module", return_value=module):
            web.chat_memory_modules["failure"] = web.ChatSession("fact_store")
        with patch.object(ReAct, "client", FakeOpenAIClient()), patch.object(web.app.logger, "exception"):
            response = web.app.test_client().post("/get", json={"chat_id": "failure", "memory_module": "fact_store", "message": "new"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(module.retrieve("cat", 1)[0].text, "cat")
        web.chat_memory_modules.clear()


if __name__ == "__main__":
    unittest.main()
