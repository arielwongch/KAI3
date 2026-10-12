"""Opt-in real CPU model check: python tests/smoke_reranker_memory.py.

Downloads embedding and pinned reranker weights on first use. No LLM/API calls.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from MemoryEntry import MemoryEntry
from VectorStoreReranker import VectorStoreReranker


def main():
    memory = VectorStoreReranker(candidate_k=None)
    memory.write(MemoryEntry('I enjoy reading science fiction novels.', {'id': 'books'}))
    memory.write(MemoryEntry('I avoid meat and follow a vegetarian diet.', {'id': 'diet'}))
    result = memory.retrieve('What kinds of books do I enjoy?', 1)
    assert result[0].metadata['id'] == 'books', result
    long_text = 'The weather is cloudy with mild temperatures. ' * 100
    long_text += ' The deployment access code is sapphire.'
    memory.write(MemoryEntry(long_text, {'id': 'long'}))
    result = memory.retrieve('What is the deployment access code?', 1)
    assert result[0].metadata['id'] == 'long', result
    assert result[0].text == long_text
    assert result[0].metadata['retrieval_score_type'] == 'cross_encoder_logit'
    print('PASS: real reranker paraphrase retrieval and late evidence in a whole long turn')


if __name__ == '__main__':
    main()
