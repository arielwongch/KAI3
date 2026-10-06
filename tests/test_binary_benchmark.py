import json
import os
import sys
import unittest
import tempfile
from unittest.mock import patch
sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import Benchmark
from benchmark_helpers import FakeTokenizer
from test_memory_integration import FakeOpenAIClient


def judgment(correct):
    return json.dumps(dict(correct=correct, correctness=2, completeness=2,
                           support=0, abstention=0, overall=2,
                           rationale='Equivalent answer.', uncertain=False))


class BinaryBenchmarkTests(unittest.TestCase):
    def setUp(self):
        import app
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store_patch = patch.object(app, 'RUN_STORE', directory.name)
        store_patch.start(); self.addCleanup(store_patch.stop)
        app.jobs.clear(); self.addCleanup(app.jobs.clear)
        token_patch = patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer())
        token_patch.start(); self.addCleanup(token_patch.stop)

    def test_question_only_isolation_and_binary_aggregation(self):
        data = [dict(sample_id=str(i), conversation={
            'session_1': [dict(speaker='Alice', text='SECRET HISTORY', dia_id='D1:1')]},
            qa=[dict(question='Where?', answer='SECRET REFERENCE', category=4)]) for i in range(2)]
        fake = FakeOpenAIClient(['Rome', judgment(1), 'Unknown', judgment(0)])
        job = Benchmark.BenchmarkJob(data, dict(module='no_memory', no_memory_context='question_only', all_conversations=True, question_limit=0))
        with patch.object(Benchmark, 'client', fake):
            job.run()
        result = job.snapshot()
        self.assertEqual(result['status'], 'completed')
        for call in fake.calls[::2]:
            self.assertNotIn('SECRET', str(call))
        for memory in result['memories']:
            self.assertEqual(memory['memory']['entries'], [])
        for case in result['cases']:
            self.assertEqual(case['diagnostics']['retrieved'], [])
            self.assertEqual(case['diagnostics']['stored_after'], 0)
        for row in result['scores']:
            self.assertEqual(row['accuracy'], .5)
            self.assertEqual(row['scored_count'], 2)
            self.assertEqual(row['correct_count'], 1)

    def test_full_context_fresh_requests_and_numeric_session_order(self):
        conversation = {'session_10': [dict(speaker='Bob', text='LAST', dia_id='D10:1')],
                        'session_2_date_time': '7 May 2023',
                        'session_2': [dict(speaker='Alice', text='FIRST', dia_id='D2:1', blip_caption='CITY')]}
        data = [dict(sample_id='one', conversation=conversation, qa=[
            dict(question='First question?', answer='REFERENCE SECRET', category=4),
            dict(question='Second question?', answer='OTHER REFERENCE', category=4)])]
        fake = FakeOpenAIClient(['PRIOR ANSWER', judgment(1), 'NEXT ANSWER', judgment(0)])
        job = Benchmark.BenchmarkJob(data, dict(module='no_memory', question_limit=0))
        with patch.object(Benchmark, 'client', fake):
            job.run()
        result = job.snapshot()
        self.assertEqual(result['status'], 'completed')
        for call in fake.calls[::2]:
            self.assertEqual(len(call['messages']), 2)
            prompt = call['messages'][1]['content']
            self.assertLess(prompt.index('FIRST'), prompt.index('LAST'))
            for text in ('Alice', 'Bob', '7 May 2023', 'D2:1', 'CITY'):
                self.assertIn(text, prompt)
            self.assertNotIn('REFERENCE', prompt)
        second = str(fake.calls[2])
        self.assertNotIn('PRIOR ANSWER', second)
        self.assertNotIn('First question?', second)
        self.assertEqual(result['memories'][0]['memory']['entries'], [])
        self.assertEqual(result['cases'][1]['diagnostics']['retrieved'], [])

    def test_context_overflow_skips_api_and_is_reported(self):
        data = [dict(sample_id='one', conversation={'session_1': [
            dict(speaker='Alice', text='Long conversation' * 100, dia_id='D1:1')]},
            qa=[dict(question='Where?', answer='Rome', category=4)])]
        fake = FakeOpenAIClient()
        job = Benchmark.BenchmarkJob(data, dict(module='no_memory', context_limit=1500, max_output_tokens=100))
        with patch.object(Benchmark, 'client', fake):
            job.run()
        result = job.snapshot()
        self.assertEqual(fake.calls, [])
        self.assertEqual(result['cases'][0]['diagnostics']['status'], 'context_limit_exceeded')
        for row in result['scores']:
            self.assertIsNone(row['accuracy'])
            self.assertEqual(row['context_limit_count'], 1)
            self.assertEqual(row['unscored_count'], 1)

    def test_frontend_uses_full_context_default(self):
        import app
        class Worker:
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                self.target()
        fake = FakeOpenAIClient(['Rome', judgment(1)])
        data = [dict(sample_id='one', conversation={'session_1': [
            dict(speaker='Alice', text='I live in Rome.', dia_id='D1:1')]},
            qa=[dict(question='Where?', answer='Rome', category=4)])]
        with patch.object(app, 'persist_benchmark'), patch.object(app, 'Thread', Worker), patch.object(Benchmark, 'client', fake):
            response = app.app.test_client().post('/api/benchmarks', json=dict(dataset=data, options=dict(module='no_memory')))
        self.assertEqual(response.status_code, 202)
        result = app.app.test_client().get('/api/benchmarks/' + response.json['run_id']).json
        self.assertEqual(result['config']['no_memory_context'], 'full')
        self.assertIn('I live in Rome.', fake.calls[0]['messages'][1]['content'])
        self.assertEqual(result['scores'][0]['accuracy'], 1)
        page = app.app.test_client().get('/benchmark').get_data(as_text=True)
        self.assertIn('value="full_context"', page)
        self.assertIn('value="question_only"', page)

    def test_external_memory_isolation_no_qa_writes_and_metrics(self):
        from VectorStore import VectorStore
        class Embedder:
            def chunks(self, text):
                return [text]
            def embed(self, texts):
                return [[1., 0.] for text in texts]
        stores = []
        def create(*args, **kwargs):
            store = VectorStore(Embedder())
            stores.append(store)
            return store
        data = [dict(sample_id=str(i), conversation={
            'session_2': [dict(speaker='Bob', text=f'SECOND {i}', dia_id='D2:1')],
            'session_1_date_time': '7 May 2023',
            'session_1': [dict(speaker='Alice', text=f'FIRST {i}', dia_id='D1:1')]},
            qa=[dict(question='Where?', answer='REFERENCE', category=4, evidence=['D1:1'])]) for i in range(2)]
        fake = FakeOpenAIClient(['PREDICTION ONE', judgment(1), 'PREDICTION TWO', judgment(0)])
        job = Benchmark.BenchmarkJob(data, dict(module='vector_store', all_conversations=True))
        with patch.object(Benchmark.MemoryFactory, 'create_memory_module', side_effect=create), patch.object(Benchmark, 'client', fake):
            job.run()
        result = job.snapshot()
        self.assertEqual(len(stores), 2)
        self.assertEqual(result['condition'], 'vector_store')
        for i, store in enumerate(stores):
            entries = store.inspect()['entries']
            self.assertEqual(len(entries), 2)
            self.assertIn(f'FIRST {i}', entries[0]['text'])
            self.assertIn('7 May 2023', entries[0]['text'])
            self.assertNotIn('retrieval_score', entries[0]['metadata'])
            call = fake.calls[i * 2]
            self.assertEqual(call['messages'][0]['content'], Benchmark.ANSWER_SYSTEM)
            self.assertNotIn('REFERENCE', str(call))
            self.assertNotIn(f'FIRST {1-i}', str(call))
        for case in result['cases']:
            d = case['diagnostics']
            self.assertEqual(d['stored_before'], d['stored_after'])
            self.assertEqual(case['evidence_recall'], 1)
            self.assertGreater(d['memory_context_tokens'], 0)
            self.assertEqual([e['rank'] for e in d['retrieved']], [1, 2])
            self.assertEqual(d['retrieved'][0]['retrieval_score'], 1)
        for memory in result['memories']:
            growth = memory['ingestion']['storage_growth']
            self.assertEqual([g['stored_entries'] for g in growth], [0, 1, 2])
            self.assertGreater(growth[-1]['stored_text_bytes'], growth[1]['stored_text_bytes'])
        self.assertEqual(result['efficiency'][0]['mean_evidence_recall'], 1)

    def test_invalid_binary_judgment_remains_unscored(self):
        data = [dict(sample_id='one', conversation={}, qa=[dict(question='Unknown?', category=5)])]
        fake = FakeOpenAIClient(['No information available.', judgment(True)])
        job = Benchmark.BenchmarkJob(data, dict(module='no_memory'))
        with patch.object(Benchmark, 'client', fake):
            job.run()
        result = job.snapshot()
        self.assertIsNone(result['cases'][0]['correct'])
        self.assertIn('judge_error', result['cases'][0])
        self.assertIsNone(result['scores'][0]['accuracy'])
        self.assertEqual(result['scores'][0]['unscored_count'], 1)
        self.assertIsNone(json.loads(fake.calls[1]['messages'][1]['content'])['reference_answer'])

if __name__ == '__main__':
    unittest.main()
