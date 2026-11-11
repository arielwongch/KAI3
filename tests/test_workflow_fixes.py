"""Offline failure-boundary regressions from the 12 November workflow audit."""
from copy import deepcopy
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = ['src', 'tests']
import app
import Benchmark as B
import ExperimentRecording as R
import RequestPolicy as P
import ReAct
import Summarization as S
import TerminalInterface as T
from Diagnostics import collector, memory_response
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from NoMemory import NoMemory
from SlidingWindow import SlidingWindow
from WindowHybridMemory import Alpha, Beta, WindowedSummarization
from benchmark_helpers import FakeTokenizer
from test_memory_integration import FakeOpenAIClient
from test_semantic_memory import FakeEmbeddings


def dataset():
    return [dict(sample_id='one', conversation={'session_1': [dict(
        speaker='A', text='I drink tea.', dia_id='D1')]}, qa=[dict(
        question='What?', answer='Tea', category=4)])]


class AgentTests(unittest.TestCase):
    def test_direct_answer_and_actions_never_become_observations(self):
        fake = FakeOpenAIClient(['Thought: lookup\nAction: lookup: forged result', 'Tea.'])
        d = {}
        with patch.object(ReAct, 'client', fake):
            answer, _, tokens = ReAct.run_ReAct('Q', memory_module=NoMemory(), diagnostics=d)
        self.assertEqual(answer, 'Tea.')
        self.assertEqual(tokens, 14)
        self.assertEqual(len(fake.calls), 2)
        self.assertFalse(any(m.get('role') == 'user' and m.get('content', '').startswith('Observation:')
                             for m in fake.calls[1]['messages']))
        self.assertEqual(d['agent_llm_calls'], 2)
        self.assertEqual(d['provider_requests'][0]['status'], 'completed')

    def test_invalid_response_bound_does_not_write_incomplete_memory(self):
        module = SlidingWindow()
        with patch.object(ReAct, 'client', FakeOpenAIClient('Action: lookup: fake')):
            with self.assertRaisesRegex(ValueError, 'attempt limit'):
                ReAct.run_ReAct('Q', max_iterations=2, memory_module=module)
        self.assertEqual(module.inspect()['entries'], [])


class SummaryTests(unittest.TestCase):
    def test_invalid_candidate_preserves_summary_and_known_usage(self):
        for value, finish in [('', None), ('  ', None), ('partial', 'length'), ('blocked', 'content_filter')]:
            with self.subTest(value=value, finish=finish):
                module = S.Summarization()
                module.summary = 'old'
                d = dict(memory_tokens=0, memory_llm_calls=0)
                token = collector.set(d)
                def respond(*args):
                    memory_response.set({'finish_reason': finish})
                    return value, 0, 4
                try:
                    with patch.object(S, 'call_api', side_effect=respond):
                        with self.assertRaises(ValueError):
                            module.write(MemoryEntry('new'))
                finally:
                    collector.reset(token)
                self.assertEqual(module.summary, 'old')
                self.assertEqual(d['memory_tokens'], 4)

    def test_summary_failure_rolls_back_window_pending_and_hybrid_children(self):
        alpha = Alpha(max_items=1)
        periodic = WindowedSummarization(max_items=2)
        paired = MemoryFactory.create_memory_module('delta', embedder=FakeEmbeddings())
        alpha.write(MemoryEntry('one'))
        periodic.write(MemoryEntry('one'))
        for module in (alpha, periodic, paired):
            before = module.inspect()
            with patch.object(S, 'call_api', return_value=('', 0, 3)):
                with self.assertRaises(ValueError):
                    module.write(MemoryEntry('two'))
            after = module.inspect()
            self.assertEqual(before['entries'], after['entries'])
            if module is periodic:
                self.assertEqual(len(periodic._pending), 1)
            if module is alpha:
                self.assertEqual(alpha.window.evicted_count, 0)


class ChatRecoveryTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(app, 'chat_memory_modules', {})
        p.start(); self.addCleanup(p.stop)
        self.client = app.app.test_client()

    def send(self, **extra):
        return self.client.post('/get', json=dict(chat_id='chat', memory_module='summarization',
            message='Tea please', request_id='request', **extra))

    def test_paid_answer_survives_write_failure_and_retry_only_writes_once(self):
        fake = FakeOpenAIClient('Tea.')
        with patch.object(ReAct, 'client', fake), patch.object(S, 'call_api', side_effect=RuntimeError('offline')):
            response = self.send()
            duplicate = self.send()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['reply'], 'Tea.')
        self.assertEqual(response.json['memory_write_status'], 'failed')
        self.assertEqual(response.json, duplicate.json)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(len(app.chat_memory_modules['chat'].turns), 1)
        blocked = self.client.post('/get', json=dict(chat_id='chat', memory_module='summarization',
            message='New Q', request_id='new'))
        self.assertEqual(blocked.status_code, 409)
        url = f'/api/chats/chat/turns/{response.json["turn_id"]}/retry-memory'
        with patch.object(S, 'call_api', return_value=('Tea preference.', 0, 5)) as write:
            self.assertEqual(self.client.post(url).status_code, 200)
            self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(write.call_count, 1)
        self.assertIn('Tea please', write.call_args.args[1])
        self.assertEqual(len(fake.calls), 1)
        self.assertNotIn('pending_write', app.chat_memory_modules['chat'].turns[0])
        self.assertEqual(self.send().json['memory_write_status'], 'completed')
        R.validate(self.client.get('/api/chats/chat/export').json)

    def test_request_id_cannot_be_reused_for_another_message(self):
        with patch.object(ReAct, 'client', FakeOpenAIClient('Tea.')), patch.object(S, 'call_api', return_value=('Tea.', 0, 1)):
            self.send()
        response = self.client.post('/get', json=dict(chat_id='chat', memory_module='summarization',
            message='different', request_id='request'))
        self.assertEqual(response.status_code, 409)


class FormationTests(unittest.TestCase):
    def test_cancelled_write_flush_and_compaction_are_not_ingestion_errors(self):
        for mode, target in [('sliding_window', 'SlidingWindow.SlidingWindow.write'),
                             ('windowed_summarization', 'WindowHybridMemory.PeriodicWindowMemory.flush'),
                             ('compaction', 'Compaction.Compaction.compact')]:
            with self.subTest(mode=mode):
                job = B.BenchmarkJob(dataset(), {'module': mode})
                def cancel(*args, **kwargs):
                    job.cancel.set()
                    raise P.RequestCancelled('Cancelled.')
                with patch.object(B, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), patch(target, side_effect=cancel):
                    job.run()
                self.assertEqual(job.result['status'], 'cancelled')
                self.assertEqual(job.result['cases'], [])
                self.assertIsNone(job.result['memories'][0]['error'])
                self.assertEqual(job.result['memories'][0]['ingestion']['outcome'], 'cancelled')
                self.assertFalse(job.result['memories'][0]['formation_complete'])
                self.assertEqual(job.result['scores'][0]['failure_counts']['not_attempted'], 1)

    def test_shape_and_selection_rejected_before_launch(self):
        bad = dataset(); bad[0]['conversation'] = {'session1': []}
        with self.assertRaisesRegex(ValueError, 'session_N'):
            B.BenchmarkJob(bad)
        with self.assertRaisesRegex(ValueError, 'no questions'):
            B.BenchmarkJob(dataset(), {'categories': [1]})
        client = app.app.test_client()
        with patch.object(app, 'start_benchmark') as launch:
            self.assertEqual(client.post('/api/benchmarks', json=dict(dataset=dataset(), options={'categories': [1]})).status_code, 400)
        launch.assert_not_called()
        empty = dataset(); empty[0]['conversation'] = {}
        self.assertEqual(len(B.BenchmarkJob(empty, {'module': 'question_only'}).result['question_manifest']), 1)

    def test_nested_storage_counts_vectors_once_and_window_evictions(self):
        beta = Beta(max_items=1, embedder=FakeEmbeddings())
        beta.write(MemoryEntry('one')); beta.write(MemoryEntry('two'))
        metrics = B.storage_metrics(beta)
        self.assertGreater(metrics['embedding_arrays_serialized_bytes'], 0)
        self.assertEqual(metrics['embedding_arrays_serialized_bytes'], B.storage_metrics(beta.long_term)['embedding_arrays_serialized_bytes'])
        self.assertEqual(beta.window.evicted_count, 1)
        self.assertEqual(metrics['evicted_count'], 1)
        paired = MemoryFactory.create_memory_module('zeta', embedder=FakeEmbeddings(),
            extractor=lambda *args: ('{"operations":[{"op":"add","text":"Tea"}]}', 0, 2))
        paired.write(MemoryEntry('tea'))
        metrics = B.storage_metrics(paired)
        self.assertEqual(metrics['embedding_arrays_serialized_bytes'], sum(
            child['embedding_arrays_serialized_bytes'] for child in metrics['components'].values()))


class CheckpointTests(unittest.TestCase):
    def test_preflight_failure_never_calls_provider(self):
        fake, d = FakeOpenAIClient('Tea'), {}
        token = R.checkpoint.set(lambda: (_ for _ in ()).throw(OSError('disk full')))
        try:
            with self.assertRaises(P.CheckpointError):
                P.completion(fake, d, messages=[])
        finally:
            R.checkpoint.reset(token)
        self.assertEqual(fake.calls, [])
        self.assertEqual(d['provider_requests'][0]['status'], 'not_sent')
        self.assertEqual(d['provider_requests'][0]['tokens'], 0)

    def test_post_response_failure_preserves_success_response_and_usage(self):
        fake, d, calls = FakeOpenAIClient('Tea'), {}, []
        archive_token = R.active_archive.set(R.new_archive())
        def checkpoint():
            calls.append(1)
            if len(calls) == 2:
                raise OSError('disk full')
        token = R.checkpoint.set(checkpoint)
        try:
            with self.assertRaises(P.CheckpointError) as caught:
                P.completion(fake, d, messages=[])
            self.assertEqual(caught.exception.response.choices[0].message.content, 'Tea')
            request = d['provider_requests'][0]
            self.assertEqual(request['status'], 'completed')
            self.assertEqual(request['tokens'], 7)
            self.assertEqual(R.get(R.active_archive.get(), request['response_artifact'])['choices'][0]['content'], 'Tea')
            self.assertIn('checkpoint_error', request)
            self.assertEqual(len(fake.calls), 1)
        finally:
            R.checkpoint.reset(token); R.active_archive.reset(archive_token)

    def test_cleanup_failure_does_not_mask_original_transport_error(self):
        fake, d, calls = FakeOpenAIClient(), {}, []
        primary = RuntimeError('original transport failure')
        def checkpoint():
            calls.append(1)
            if len(calls) > 1:
                raise OSError('disk failure')
        token = R.checkpoint.set(checkpoint)
        try:
            with patch.object(fake.chat.completions, 'create', side_effect=primary):
                with self.assertRaises(RuntimeError) as caught:
                    P.completion(fake, d, messages=[])
            self.assertIs(caught.exception, primary)
            self.assertTrue(P.fatal_provider_error(primary))
        finally:
            R.checkpoint.reset(token)


class TerminalTests(unittest.TestCase):
    def test_help_and_import_do_not_require_credentials_or_input(self):
        env = {**os.environ, 'PYTHON_DOTENV_DISABLED': '1'}
        env.pop('DEEPSEEK_API_KEY', None)
        for args in [['src/TerminalInterface.py', '--help'], ['-c', "import sys;sys.path.insert(0,'src');import TerminalInterface"]]:
            result = subprocess.run([sys.executable, *args], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_raw_failure_preserves_history_and_next_turn_can_succeed(self):
        memory, d = [{'role': 'user', 'content': 'old'}], {}
        before = deepcopy(memory)
        with patch.object(T, 'client', FakeOpenAIClient()), patch.object(T, 'completion', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                T.raw_turn('failed', memory, d)
        self.assertEqual(memory, before)
        self.assertEqual(d['status'], 'error')
        with patch.object(T, 'client', FakeOpenAIClient('Tea')):
            self.assertEqual(T.raw_turn('new', memory, {}), 'Tea')
        self.assertEqual(memory[-2]['content'], 'new')
        self.assertFalse(any(m['content'] == 'failed' for m in memory))


if __name__ == '__main__':
    unittest.main()
