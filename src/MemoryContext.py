"""Consistent context rendering for chat and direct benchmark answers."""
from SlidingWindow import SlidingWindow


def retrieval_k(module):
    return module.buffer.maxlen if isinstance(module, SlidingWindow) else 5


def format_context(entries, separator='\n\n'):
    if not any(e.metadata.get('memory_tier') for e in entries):
        return separator.join(e.text for e in entries)
    labels = {'summarization': 'Earlier conversation summary',
              'vector_store': 'Retrieved earlier conversation turns',
              'fact_store': 'Current asserted facts',
              'sliding_window': 'Recent conversation (oldest to newest)'}
    sections = []
    for component, label in labels.items():
        texts = [e.text for e in entries if e.metadata.get('memory_component') == component]
        if texts:
            sections.append(label + ':\n' + separator.join(texts))
    return ('Explicit recent corrections supersede older statements.\n\n'
            + '\n\n'.join(sections))
