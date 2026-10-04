"""LoCoMo QA protocol: direct ingestion, isolated memories, no QA write-back."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import re
import string
import threading
import time
from uuid import uuid4
from nltk.stem import PorterStemmer
from API import call_api
from Diagnostics import collector, totals
from Embeddings import MODEL_NAME
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from ReAct import run_ReAct

MODULES = ['sliding_window', 'summarization', 'vector_store', 'fact_store']
STEMMER = PorterStemmer()

def normalize(text):
    text = str(text).lower().replace(',', '')
    text = ''.join(c for c in text if c not in string.punctuation)
    return re.sub(r'\b(a|an|the|and)\b', ' ', text).split()

def f1(prediction, answer):
    p = [STEMMER.stem(t) for t in normalize(prediction)]
    a = [STEMMER.stem(t) for t in normalize(answer)]
    common = sum((Counter(p) & Counter(a)).values())
    return 2 * common / (len(p) + len(a)) if common else 0.0

def score(prediction, answer, category):
    if category == 5:
        return float(any(t in prediction.lower() for t in ('no information available', 'not mentioned')))
    if category == 1:
        answers = str(answer).split(',')
        return sum(max(f1(p.strip(), a.strip()) for p in prediction.split(',')) for a in answers) / len(answers)
    if category == 3:
        answer = str(answer).split(';')[0].strip()
    return f1(prediction, answer)

def benchmark_extractor(prompt, payload):
    return call_api(prompt + '\nThese are benchmark conversation assertions. Preserve the named speaker and dates in every fact. Both named speakers are evidence, not the assistant. Never merge facts belonging to different speakers.', payload)

def validate_dataset(data):
    if not isinstance(data, list) or not data:
        raise ValueError('Dataset must be a nonempty LoCoMo array.')
    for sample in data:
        if not isinstance(sample, dict) or not isinstance(sample.get('conversation'), dict) or not isinstance(sample.get('qa'), list) or 'sample_id' not in sample:
            raise ValueError('Each sample requires sample_id, conversation, and qa.')
        for key, turns in sample['conversation'].items():
            if re.fullmatch(r'session_\d+', key):
                if not isinstance(turns, list) or any(not isinstance(t, dict) or not all(k in t for k in ('speaker', 'text', 'dia_id')) for t in turns):
                    raise ValueError('Session turns require speaker, text, and dia_id.')
        for qa in sample['qa']:
            if not isinstance(qa, dict) or not isinstance(qa.get('question'), str) or qa.get('category') not in range(1, 6) or (qa['category'] != 5 and 'answer' not in qa):
                raise ValueError('Invalid QA question, answer, or category.')

def options_for(data, options):
    modules = options.get('modules', MODULES)
    ids = [str(s['sample_id']) for s in data] if options.get('all_conversations') else options.get('sample_ids') or [str(data[0]['sample_id'])]
    categories = options.get('categories') or [1, 2, 3, 4, 5]
    limit = options.get('question_limit', 10)
    if not isinstance(modules, list) or not modules or any(m not in MODULES for m in modules):
        raise ValueError('Select known memory modules.')
    if not isinstance(ids, list) or any(str(i) not in {str(s['sample_id']) for s in data} for i in ids):
        raise ValueError('Unknown conversation ID.')
    if not isinstance(categories, list) or any(c not in range(1, 6) for c in categories):
        raise ValueError('Categories must be 1–5.')
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError('Question limit must be nonnegative; zero means all.')
    return dict(modules=list(dict.fromkeys(modules)), sample_ids=list(ids), categories=list(categories), question_limit=limit)

class BenchmarkJob:
    def __init__(self, data, options=None):
        validate_dataset(data)
        self.data = deepcopy(data)
        self.options = options_for(data, options or {})
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.result = dict(schema_version=1, run_id=str(uuid4()), status='queued',
                           dataset_hash=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
                           config=self.options, model='deepseek-flash', embedding_model=MODEL_NAME,
                           protocol='direct-turn-ingestion; retrieval-k=5; upstream-category-QA-scoring',
                           progress={'completed': 0, 'total': 0}, cases=[], memories=[], errors=[])
    def snapshot(self):
        with self.lock:
            return deepcopy(self.result)
    def update(self, **values):
        with self.lock:
            self.result.update(values)
    def run(self):
        self.update(status='running')
        samples = [s for s in self.data if str(s['sample_id']) in self.options['sample_ids']]
        question_sets = []
        for sample in samples:
            qs = [(i, q) for i, q in enumerate(sample['qa']) if q['category'] in self.options['categories']]
            limit = self.options['question_limit']
            question_sets.append((sample, qs[:limit] if limit else qs))
        self.update(progress={'completed': 0, 'total': sum(len(qs) for _, qs in question_sets) * len(self.options['modules'])})
        try:
            for mode in self.options['modules']:
                for sample, questions in question_sets:
                    if self.cancel.is_set():
                        return
                    module = MemoryFactory.create_memory_module(mode, extractor=benchmark_extractor)
                    ingestion = dict(memory_llm_calls=0, memory_tokens=0)
                    start = time.perf_counter()
                    token = collector.set(ingestion)
                    ingestion_error = None
                    try:
                        conv = sample['conversation']
                        sessions = sorted((k for k in conv if re.fullmatch(r'session_\d+', k)), key=lambda k: int(k.split('_')[1]))
                        for session in sessions:
                            for turn in conv[session]:
                                if self.cancel.is_set():
                                    return
                                timestamp = conv.get(session + '_date_time', '')
                                text = f"[{timestamp}] {turn['speaker']}: {turn['text']}"
                                if turn.get('blip_caption'):
                                    text += '\nImage caption: ' + str(turn['blip_caption'])
                                module.write(MemoryEntry(text, dict(type='benchmark', user_text=text, speaker=turn['speaker'], timestamp=timestamp, dialogue_id=turn['dia_id'], session=session)))
                    except Exception as error:
                        ingestion_error = str(error)
                    finally:
                        collector.reset(token)
                        ingestion['total_seconds'] = time.perf_counter() - start
                        with self.lock:
                            self.result['memories'].append(dict(sample_id=sample['sample_id'], module=mode, memory=module.inspect(), ingestion=ingestion, error=ingestion_error))
                    if ingestion_error:
                        with self.lock:
                            self.result['errors'].append(dict(sample_id=sample['sample_id'], module=mode, phase='ingestion', error=ingestion_error))
                        continue
                    for index, qa in questions:
                        if self.cancel.is_set():
                            return
                        d = {}
                        case = dict(sample_id=sample['sample_id'], module=mode, question_index=index, question=qa['question'], category=qa['category'], answer=qa.get('answer'), evidence=qa.get('evidence', []), diagnostics=d, score=None, evidence_recall=None)
                        try:
                            question = qa['question'] + '\nAnswer concisely from the memories. If unavailable, answer: No information available.'
                            run_ReAct(question, memory_module=module, diagnostics=d, write_back=False)
                            case['prediction'] = d['final_answer']
                            if d['status'] == 'completed':
                                case['score'] = score(d['final_answer'], qa.get('answer', ''), qa['category'])
                            if mode in ('sliding_window', 'vector_store') and qa.get('evidence'):
                                ids = {e['metadata'].get('dialogue_id') for e in d['retrieved']}
                                case['evidence_recall'] = sum(e in ids for e in qa['evidence']) / len(qa['evidence'])
                        except Exception as error:
                            case['error'] = str(error)
                        with self.lock:
                            self.result['cases'].append(case)
                            self.result['progress']['completed'] += 1
            self.update(status='completed')
        except Exception as error:
            self.update(status='failed', error=str(error))
        finally:
            if self.cancel.is_set():
                self.update(status='cancelled')
            groups = defaultdict(list)
            for case in self.snapshot()['cases']:
                if case['score'] is not None:
                    groups[(case['module'], str(case['category']))].append(case['score'])
                    groups[(case['module'], 'overall')].append(case['score'])
            self.update(scores=[dict(module=m, category=c, mean_qa_score=sum(v)/len(v), count=len(v)) for (m, c), v in groups.items()])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--modules', nargs='+', choices=MODULES, default=MODULES)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--sample-ids', nargs='+')
    selection.add_argument('--all-conversations', action='store_true')
    parser.add_argument('--categories', nargs='+', type=int)
    parser.add_argument('--question-limit', type=int, default=10)
    args = parser.parse_args()
    with open(args.dataset) as f:
        job = BenchmarkJob(json.load(f), vars(args))
    try:
        job.run()
    except KeyboardInterrupt:
        job.cancel.set()
        job.update(status='cancelled')
    with open(args.output, 'w') as f:
        json.dump(job.snapshot(), f, indent=2)

if __name__ == '__main__':
    main()
