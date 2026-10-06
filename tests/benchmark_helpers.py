"""Offline tokenization fixture; never used in production."""
class FakeTokenizer:
    identity = dict(id='test-character-tokenizer', revision='v1', artifact_sha256='test', exact_provider_tokens=False)

    def __init__(self):
        self.tokenizer = self

    def count(self, text):
        return len(text)

    def prefix_offsets(self, text):
        return list(range(1, len(text) + 1))

    def encode(self, text, **kwargs):
        return list(text)

    def decode(self, tokens, **kwargs):
        return ''.join(tokens)
