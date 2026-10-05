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
from API import call_api, client
from Diagnostics import collector
from Embeddings import MODEL_NAME
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from NoMemory import NoMemory

MODULES = ['sliding_window', 'summarization', 'vector_store', 'fact_store', 'no_memory']
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

def abstained(prediction):
    text = str(prediction).lower()
    return any(phrase in text for phrase in ('no information available', 'not mentioned', 'cannot determine', 'unable to answer'))

def answer_variants(answer, category):
    if category == 5:
        return []
    if category == 1:
        return [v.strip() for v in str(answer).split(',')]
    if category == 3:
        return [str(answer).split(';')[0].strip()]
    return [str(answer)]

def exact_match(prediction, answer, category):
    if category == 5:
        return float(abstained(prediction))
    return float(any(normalize(prediction) == normalize(v) for v in answer_variants(answer, category)))

def token_f1(prediction, answer, category):
    if category == 5:
        return float(abstained(prediction))
    return max((f1(prediction, v) for v in answer_variants(answer, category)), default=0.0)

def direct_answer(module, question, diagnostics):
    started = time.perf_counter()
    entries = module.retrieve(query=question, k=5)
    diagnostics['retrieval_seconds'] = time.perf_counter() - started
    diagnostics['retrieved'] = [dict(text=e.text, metadata=e.metadata) for e in entries]
    diagnostics['retrieved_count'] = len(entries)
    context = '\n\n'.join(e.text for e in entries) or '(No memories retrieved.)'
    system = ('Answer the question using the supplied conversation memories. '
              'Be concise. If the answer is not supported by the memories, say '
              '"No information available." Do not invent facts.')
    started = time.perf_counter()
    diagnostics['answer_llm_calls'] = 1
    response = client.chat.completions.create(
        model='deepseek-flash',
        messages=[{'role': 'system', 'content': system},
                  {'role': 'user', 'content': f'Memories:\n{context}\n\nQuestion: {question}'}],
        stream=False, reasoning_effort='high', extra_body={'thinking': {'type': 'enabled'}},
    )
    diagnostics['answer_seconds'] = time.perf_counter() - started
    diagnostics['answer_tokens'] = getattr(getattr(response, 'usage', None), 'total_tokens', None)
    return (response.choices[0].message.content or '').strip()

JUDGE_PROMPT_VERSION = 'locomo-judge-v1'
def judge_answer(question, reference, prediction, evidence):
    system = '''You are a strict evaluator for conversational memory QA. Judge only the answer's correctness, completeness, and support from the supplied evidence. For unanswerable/adversarial questions, reward appropriate abstention and penalize invented details. Do not reward fluent wording by itself. Return only JSON with integer 0, 1, or 2 for correctness, completeness, support, and abstention (0=poor, 1=partial, 2=good), plus overall (0-2), rationale (short string), and uncertain (boolean).'''
    payload = json.dumps({'question': question, 'reference_answer': reference,
                          'prediction': prediction, 'evidence': evidence}, ensure_ascii=False)
    started = time.perf_counter()
    response = client.chat.completions.create(
        model='deepseek-flash', messages=[{'role':'system','content':system},
                                          {'role':'user','content':payload}],
        stream=False, response_format={'type':'json_object'},
    )
    elapsed = time.perf_counter() - started
    usage = getattr(response, 'usage', None)
    raw = (response.choices[0].message.content or '{}').strip()
    parsed = json.loads(raw)
    for key in ('correctness', 'completeness', 'support', 'abstention', 'overall'):
        if parsed.get(key) not in (0, 1, 2):
            raise ValueError(f'Invalid judge field: {key}')
    if not isinstance(parsed.get('rationale'), str) or not isinstance(parsed.get('uncertain'), bool):
        raise ValueError('Invalid judge rationale or uncertainty field.')
    return parsed, elapsed, getattr(usage, 'total_tokens', None)

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
    modules = options.get('modules', [options.get('module', MODULES[0])])
    if isinstance(modules, str):
        modules = [modules]
    ids = [str(s['sample_id']) for s in data] if options.get('all_conversations') else options.get('sample_ids') or [str(data[0]['sample_id'])]
    categories = options.get('categories') or [1, 2, 3, 4, 5]
    limit = options.get('question_limit', 10)
    if not isinstance(modules, list) or len(modules) != 1 or any(m not in MODULES for m in modules):
        raise ValueError('Select exactly one known memory module per run.')
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
        self._persistence_callback = None
        self.result = dict(schema_version=1, run_id=str(uuid4()), status='queued',
                           dataset_hash=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
                           config=self.options, model='deepseek-flash', embedding_model=MODEL_NAME,
                           protocol='direct-turn-ingestion; direct-chat-completion; retrieval-k=5; no-qa-writeback',
                           answer_model='deepseek-flash', judge_model='deepseek-flash', judge_prompt_version=JUDGE_PROMPT_VERSION,
                           progress={'completed': 0, 'total': 0}, cases=[], memories=[], errors=[])
    @classmethod
    def restore(cls, result):
        job = cls.__new__(cls)
        job.data = []
        job.options = result.get('config', {})
        job.lock = threading.RLock()
        job.cancel = threading.Event()
        job._persistence_callback = None
        job.result = deepcopy(result)
        if job.result.get('status') in ('queued', 'running'):
            job.result['status'] = 'interrupted'
            job.result['error'] = 'The server restarted while this run was active. Partial results are available.'
        return job
    def set_persistence_callback(self, callback):
        self._persistence_callback = callback
    def persist(self):
        callback = self._persistence_callback
        if callback:
            callback(self.snapshot())
    def snapshot(self):
        with self.lock:
            return deepcopy(self.result)
    def update(self, **values):
        with self.lock:
            self.result.update(values)
        self.persist()
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
                    module = NoMemory() if mode == 'no_memory' else MemoryFactory.create_memory_module(mode, extractor=benchmark_extractor)
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
                        self.persist()
                    if ingestion_error:
                        with self.lock:
                            self.result['errors'].append(dict(sample_id=sample['sample_id'], module=mode, phase='ingestion', error=ingestion_error))
                        continue
                    for index, qa in questions:
                        if self.cancel.is_set():
                            return
                        d = {}
                        case = dict(sample_id=sample['sample_id'], module=mode, question_index=index, question=qa['question'], category=qa['category'], answer=qa.get('answer'), evidence=qa.get('evidence', []), diagnostics=d, score=None, exact_match=None, token_f1=None, judge=None, evidence_recall=None)
                        try:
                            case_started = time.perf_counter()
                            d.update(status='running', query=qa['question'], answer_tokens=0, judge_tokens=0,
                                     judge_seconds=0.0, judge_llm_calls=0)
                            d['stored_before'] = len(module.inspect()['entries'])
                            d['final_answer'] = direct_answer(module, qa['question'], d)
                            d.update(status='completed', answer_status='completed')
                            case['prediction'] = d['final_answer']
                            case['score'] = score(d['final_answer'], qa.get('answer', ''), qa['category'])
                            case['exact_match'] = exact_match(d['final_answer'], qa.get('answer', ''), qa['category'])
                            case['token_f1'] = token_f1(d['final_answer'], qa.get('answer', ''), qa['category'])
                            try:
                                judge, elapsed, tokens = judge_answer(qa['question'], qa.get('answer'), d['final_answer'], [e['text'] for e in d['retrieved']])
                                d['judge_llm_calls'] = 1; d['judge_seconds'] = elapsed; d['judge_tokens'] = tokens
                                case['judge'] = judge
                            except Exception as judge_error:
                                case['judge_error'] = str(judge_error)
                                d['judge_status'] = 'error'
                            d['total_seconds'] = time.perf_counter() - case_started
                            d['stored_after'] = len(module.inspect()['entries'])
                            if mode in ('sliding_window', 'vector_store') and qa.get('evidence'):
                                ids = {e['metadata'].get('dialogue_id') for e in d['retrieved']}
                                case['evidence_recall'] = sum(e in ids for e in qa['evidence']) / len(qa['evidence'])
                        except Exception as error:
                            case['error'] = str(error)
                            d.update(status='error', error=str(error), total_seconds=time.perf_counter() - case_started)
                        with self.lock:
                            self.result['cases'].append(case)
                            self.result['progress']['completed'] += 1
                        if self.result['progress']['completed'] % 5 == 0:
                            self.persist()
            self.update(status='completed')
        except Exception as error:
            self.update(status='failed', error=str(error))
        finally:
            if self.cancel.is_set():
                self.update(status='cancelled')
            groups = defaultdict(list)
            exact_groups = defaultdict(list)
            f1_groups = defaultdict(list)
            judge_groups = defaultdict(list)
            for case in self.snapshot()['cases']:
                if case['score'] is not None:
                    groups[(case['module'], str(case['category']))].append(case['score'])
                    groups[(case['module'], 'overall')].append(case['score'])
                for field, target in (('exact_match', exact_groups), ('token_f1', f1_groups)):
                    if case.get(field) is not None:
                        target[(case['module'], str(case['category']))].append(case[field])
                        target[(case['module'], 'overall')].append(case[field])
                if case.get('judge'):
                    judge_groups[(case['module'], str(case['category']))].append(case['judge']['overall'])
                    judge_groups[(case['module'], 'overall')].append(case['judge']['overall'])
            summaries = []
            for key in dict.fromkeys([*groups, *exact_groups, *f1_groups, *judge_groups]):
                m, c = key
                summaries.append(dict(module=m, category=c,
                    mean_qa_score=(sum(groups[key])/len(groups[key]) if groups.get(key) else None),
                    mean_exact_match=(sum(exact_groups[key])/len(exact_groups[key]) if exact_groups.get(key) else None),
                    mean_token_f1=(sum(f1_groups[key])/len(f1_groups[key]) if f1_groups.get(key) else None),
                    mean_judge=(sum(judge_groups[key])/len(judge_groups[key]) if judge_groups.get(key) else None),
                    answer_count=len(groups.get(key, [])), judge_count=len(judge_groups.get(key, []))))
            self.update(scores=summaries)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--modules', nargs='+', choices=MODULES, default=[MODULES[0]], help='Select exactly one memory architecture per run.')
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
