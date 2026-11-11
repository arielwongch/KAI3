"""Exact-result caching and aggregation must avoid audit-payload work."""
from concurrent.futures import ThreadPoolExecutor
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import Benchmark
import ExperimentRecording as recording
from AuditProvenance import memory_identity
from BenchmarkStore import write_snapshot, read_json
from Compaction import Compaction
from MemoryEntry import MemoryEntry
from benchmark_helpers import FakeTokenizer
from test_binary_benchmark import judgment
from test_memory_integration import FakeOpenAIClient


def dataset():
    return [dict(sample_id='one', conversation={'session_1': [
        dict(speaker='Alice', text='I live in Rome.', dia_id='D1:1')]},
        qa=[dict(question=f'Where {i}?', answer='Rome', category=4) for i in range(2)])]


class RuntimeOptimizationTests(unittest.TestCase):
    def test_parallel_token_count_cache_preserves_identity_and_counts_once(self):
        base = FakeTokenizer()
        cached = Benchmark.CachedTokenizer(base)
        barrier = threading.Barrier(4)
        def count():
            barrier.wait(5)
            return cached.count('same context')
        with patch.object(base, 'count', wraps=base.count) as underlying, \
             ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(count) for _ in range(4)]
            self.assertEqual([future.result() for future in futures], [12] * 4)
        underlying.assert_called_once_with('same context')
        self.assertEqual(cached.identity, base.identity)
        self.assertEqual(cached.prefix_offsets('文件'), base.prefix_offsets('文件'))

    def test_cache_is_bounded_and_eviction_does_not_change_results(self):
        base = FakeTokenizer()
        cached = Benchmark.CachedTokenizer(base, max_bytes=32, max_entries=2)
        for text in ('aaa', 'bbb', 'ccc', '文件', 'x' * 100, 'aaa'):
            self.assertEqual(cached.count(text), base.count(text))
            self.assertLessEqual(cached._bytes, 32)
            self.assertLessEqual(len(cached._counts), 2)
        self.assertNotIn('x' * 100, cached._counts)

    def test_source_is_captured_once_and_compaction_envelope_matches_existing_codec(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='compaction'))
        module = Compaction(tokenizer=FakeTokenizer())
        module.write(MemoryEntry('Rome', {'dialogue_id': 'D1:1'}))
        sample = job.data[0]
        ingestion = dict(ingestion_id='build', memory_llm_calls=0, memory_tokens=0)
        expected = module.export_state()
        expected.pop('recording')
        identity = memory_identity(module)
        entries = Benchmark.conversation_entries
        with patch.object(Benchmark, 'conversation_entries', wraps=entries) as source, \
             patch.object(module, 'export_state', side_effect=AssertionError('Copied audit payloads only to discard them')):
            first = job.record_memory(module, sample, 'compaction', ingestion)
            second = job.record_memory(module, sample, 'compaction', ingestion)
        self.assertEqual(source.call_count, 1)
        self.assertEqual(first['source_artifact'], second['source_artifact'])
        self.assertEqual(second['compaction_artifact'], expected)
        self.assertEqual(second['identity'], identity)
        recording.validate(job.result)

    def test_finalization_and_checkpointing_never_deepcopy_unrelated_audit_payloads(self):
        class NoCopy(dict):
            def __deepcopy__(self, memo):
                raise AssertionError('Finalization copied audit payloads')
        job = Benchmark.BenchmarkJob(dataset(), dict(module='question_only', question_limit=0))
        obj = dict(kind='diagnostic', value=NoCopy(text='large archived payload' * 10000))
        identity = recording.sha256(obj)
        job.result['recording']['artifacts'][identity] = obj
        fake = FakeOpenAIClient(['Rome', judgment(1), 'Rome', judgment(0)])
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, job.result['run_id'] + '.json')
            job.set_persistence_callback(lambda value: write_snapshot(path, value))
            with patch.object(Benchmark, 'client', fake):
                job.run()
            self.assertEqual(job.result['status'], 'completed', job.result.get('error'))
            overall = next(row for row in job.result['scores'] if row['category'] == 'overall')
            self.assertEqual(overall['accuracy'], .5)
            restored = read_json(path)
            recording.validate(restored)
            self.assertEqual(recording.get(restored['recording'], {'artifact_sha256': identity}), obj['value'])


if __name__ == '__main__':
    unittest.main()
