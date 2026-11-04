"""Slow memory initialization must not stall independent workspace requests."""
import os
import sys
import unittest
import gc
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from weakref import WeakValueDictionary

os.environ['DEEPSEEK_API_KEY'] = 'test-only'
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
sys.path.insert(0, 'src')
import app


class ChatConcurrencyTests(unittest.TestCase):
    def setUp(self):
        for name, value in (('chat_memory_modules', {}),
                            ('chat_initialization_locks', WeakValueDictionary())):
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def send(chat_id, mode='no_memory'):
        with app.app.test_client() as client:
            return client.post('/get', json=dict(
                chat_id=chat_id, memory_module=mode, message='hello'))

    def test_slow_initialization_does_not_block_another_chat_or_diagnostics(self):
        entered, release = Event(), Event()
        original = app.ChatSession

        def create(mode, *args):
            if mode == 'sliding_window':
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('Test did not release initialization')
            return original(mode, *args)

        with patch.object(app, 'ChatSession', side_effect=create), patch.object(
                app, 'run_ReAct', return_value=('ready', 0, 0)), ThreadPoolExecutor(3) as pool:
            slow = pool.submit(self.send, 'slow', 'sliding_window')
            try:
                self.assertTrue(entered.wait(2))
                fast = pool.submit(self.send, 'fast')
                self.assertEqual(fast.result(timeout=2).status_code, 200)

                def inspect():
                    with app.app.test_client() as client:
                        return client.get('/api/chats/fast')

                self.assertEqual(pool.submit(inspect).result(timeout=2).status_code, 200)
            finally:
                release.set()
            self.assertEqual(slow.result(timeout=2).status_code, 200)

    def test_missing_restored_chats_do_not_retain_initialization_locks(self):
        with app.app.test_client() as client:
            for index in range(3):
                response = client.post('/get', json=dict(chat_id=f'missing-{index}',
                    memory_module='no_memory', message='hello', requires_existing=True))
                self.assertEqual(response.status_code, 410)
        gc.collect()
        self.assertEqual(len(app.chat_initialization_locks), 0)
        self.assertEqual(app.chat_memory_modules, {})

    def test_failed_initialization_does_not_retain_lock(self):
        with patch.object(app, 'ChatSession', side_effect=ValueError('Invalid settings')):
            self.assertEqual(self.send('invalid').status_code, 400)
        gc.collect()
        self.assertEqual(len(app.chat_initialization_locks), 0)

    def test_simultaneous_first_messages_share_one_memory_module(self):
        entered, release = Event(), Event()
        original = app.ChatSession

        def create(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Test did not release initialization')
            return original(*args)

        with patch.object(app, 'ChatSession', side_effect=create) as constructor, patch.object(
                app, 'run_ReAct', return_value=('ready', 0, 0)), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.send, 'shared')
            try:
                self.assertTrue(entered.wait(2))
                gc.collect()
                self.assertIn('shared', app.chat_initialization_locks)
                second = pool.submit(self.send, 'shared')
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2).status_code, 200)
            self.assertEqual(second.result(timeout=2).status_code, 200)
            self.assertEqual(constructor.call_count, 1)
            self.assertEqual(len(app.chat_memory_modules['shared'].turns), 2)
        gc.collect()
        self.assertEqual(len(app.chat_initialization_locks), 0)


if __name__ == '__main__':
    unittest.main()
