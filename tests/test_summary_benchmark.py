"""Summary ingestion must reach QA without one model request per dialogue turn."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import Benchmark
import Summarization
from benchmark_helpers import FakeTokenizer
from test_binary_benchmark import judgment
from test_memory_integration import FakeOpenAIClient


class SummaryBenchmarkTests(unittest.TestCase):
    def setUp(self):
        tokenizer = patch.object(Benchmark, "get_benchmark_tokenizer", return_value=FakeTokenizer())
        tokenizer.start()
        self.addCleanup(tokenizer.stop)

    def test_bundled_conversation_reaches_qa_with_batched_memory(self):
        data = json.loads(Path('data/locomo/locomo10.json').read_text())[:1]
        turns = list(Benchmark.conversation_entries(data[0]['conversation']))
        batches = list(Benchmark.ingestion_batches(data[0]['conversation'], 20))
        job = Benchmark.BenchmarkJob(data, dict(modules=['summarization'], question_limit=1))
        fake = FakeOpenAIClient(['answer', judgment(1)])
        with patch.object(Summarization, 'call_api', return_value=('remembered facts', 0, 7)) as summarize, patch.object(Benchmark, 'client', fake):
            job.run()
        result = job.snapshot()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['cases']), 1)
        self.assertEqual(result['cases'][0]['correct'], 1)
        self.assertEqual(summarize.call_count, len(batches))
        self.assertLess(summarize.call_count, len(turns) / 5)
        for call, batch in zip(summarize.call_args_list, batches):
            self.assertEqual(call.args[1].split('New interaction:\n', 1)[1], '\n\n'.join(e.text for e in batch))
        self.assertIn('remembered facts', fake.calls[0]['messages'][1]['content'])
        ingestion = result['memories'][0]['ingestion']
        self.assertEqual(ingestion['ingested_turns'], len(turns))
        self.assertEqual(ingestion['memory_llm_calls'], len(batches))
        self.assertEqual(result['progress']['ingestion_completed'], len(turns))
        self.assertEqual(result['memory_batch_settings']['max_turns'], 20)
        self.assertEqual(ingestion['storage_growth'][-1]['ingested_turns'], len(turns))

    def test_batches_preserve_turns_sessions_and_size_limits(self):
        conversation = {
            'session_10': [dict(speaker='B', dia_id='last', text='last')],
            'session_2': [dict(speaker='A', dia_id=str(i), text='x' * (150 if i == 3 else 10)) for i in range(8)],
        }
        batches = list(Benchmark.ingestion_batches(conversation, 2, 100))
        self.assertEqual([e for b in batches for e in b], list(Benchmark.conversation_entries(conversation)))
        for batch in batches:
            self.assertLessEqual(len(batch), 2)
            self.assertEqual(len({e.metadata['session'] for e in batch}), 1)
            self.assertTrue(len(batch) == 1 or len('\n\n'.join(e.text for e in batch)) <= 100)
        self.assertEqual(batches[-1][0].metadata['dialogue_id'], 'last')

    def test_per_turn_resume_retains_per_turn_ingestion(self):
        data = [dict(sample_id='one', conversation={}, qa=[])]
        previous = Benchmark.BenchmarkJob(data, dict(modules=['summarization'], summary_batch_size=1)).snapshot()
        resumed = Benchmark.BenchmarkJob.resume(data, previous)
        self.assertEqual(resumed.options['summary_batch_size'], 1)
        self.assertEqual(resumed.result['ingestion_unit'], 'turn')

    def test_new_resume_retains_batched_ingestion(self):
        data = [dict(sample_id='one', conversation={}, qa=[])]
        previous = Benchmark.BenchmarkJob(data, dict(modules=['summarization'])).snapshot()
        resumed = Benchmark.BenchmarkJob.resume(data, previous)
        self.assertEqual(resumed.options['summary_batch_size'], 20)
        self.assertEqual(resumed.result['memory_batch_settings'], previous['memory_batch_settings'])

    def test_failed_batch_does_not_count_unwritten_turns(self):
        data = [dict(sample_id='one', conversation={'session_1': [
            dict(speaker='A', dia_id=str(i), text='hello') for i in range(3)]},
            qa=[dict(question='Who?', answer='A', category=4)])]
        job = Benchmark.BenchmarkJob(data, dict(modules=['summarization']))
        with patch.object(Summarization, 'call_api', side_effect=RuntimeError('provider unavailable')):
            job.run()
        result = job.snapshot()
        self.assertEqual(result['memories'][0]['ingestion']['ingested_turns'], 0)
        self.assertEqual(result['errors'][0]['phase'], 'ingestion')
        self.assertEqual(len(result['cases']), 1)
        self.assertEqual(result['cases'][0]['case_state'], 'ingestion_blocked')
        self.assertIsNone(result['cases'][0]['correct'])


if __name__ == '__main__':
    unittest.main()
