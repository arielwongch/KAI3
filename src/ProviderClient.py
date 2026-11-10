"""One shared provider client, initialized on first use under a lock."""
from pathlib import Path
from threading import RLock


class LazyClient:
    def __init__(self, factory=None):
        self._factory = factory or self._create
        self._client = None
        self._lock = RLock()

    @staticmethod
    def _create():
        import os
        from dotenv import load_dotenv
        from openai import OpenAI
        load_dotenv(Path(__file__).with_name('.env'))
        return OpenAI(api_key=os.environ.get('DEEPSEEK_API_KEY'),
                      base_url='https://api.deepseek.com')

    def __getattr__(self, name):
        with self._lock:
            if self._client is None:
                self._client = self._factory()
            client = self._client
        return getattr(client, name)


client = LazyClient()
