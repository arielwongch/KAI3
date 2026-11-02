"""Review selection, blinding, and human calibration without model dependencies."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('audit_results', Path(__file__).resolve().parents[1]/'tools/audit_results.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def fixture():
    qa = [dict(question=f'Question {i}?', answer='Rome', category=1+i%2, evidence=['D1:1']) for i in range(7)]
    dataset = [dict(sample_id='one', qa=qa, conversation={'session_1': [dict(speaker='Alice', text='Rome', dia_id='D1:1')]})]
    reports = []
    for condition, outcomes in [('baseline', [0, 1, 0, 0, 1, 0, 1]), ('treatment', [1, 0, None, 0, 1, 0, 1])]:
        reports.append(dict(dataset_hash=audit.hashlib.sha256(json.dumps(dataset,sort_keys=True).encode()).hexdigest(), cases=[dict(**q, sample_id='one', question_index=i,
            correct=outcomes[i], prediction='Rome', judge={'rationale': 'SECRET JUDGE'},
            module=condition, evidence_complete=i==3,
            diagnostics={'supplied_context': 'Alice: Rome'}) for i,q in enumerate(qa)]))
    return *reports, dataset


class AuditResultsTests(unittest.TestCase):
    def prepare(self, **kwargs):
        return audit.prepare(*fixture(), dict(baseline='a', treatment='b', dataset='c'), **kwargs)

    def label(self, template, **values):
        row = deepcopy(template['reviews'][0])
        row.update(reviewer_id='human-1', reviewed_at='2026-11-03T12:00:00+08:00',
                   provenance='human_review', correct=1, reference_ambiguity=False,
                   failure_stage='unresolved', notes='Reviewed source conversation.')
        row.update(values)
        return dict(schema_version=audit.VERSION, packet_sha256=template['packet_sha256'], reviews=[row])

    def test_selection_reproducible_and_blinded(self):
        packet, key, template = self.prepare(agreements_per_category=1)
        self.assertEqual((packet,key,template), self.prepare(agreements_per_category=1))
        self.assertEqual(key['selection']['priority_questions'], 4)
        self.assertEqual(key['selection']['selected_questions'], 6)
        serialized = json.dumps(packet)
        for secret in ('SECRET JUDGE', 'original_correct', 'baseline', 'treatment', 'gain', 'regression'):
            self.assertNotIn(secret, serialized)
        self.assertEqual(len(packet['conversations']), 1)
        self.assertTrue(all(r['correct'] is None for r in template['reviews']))

    def test_unknown_labels_remain_pending(self):
        packet,key,template=self.prepare()
        report=audit.summarize(packet,key,[template])
        self.assertEqual(report['totals']['reviewed_answers'],0)
        self.assertEqual(report['totals']['pending_answers'],14)

    def test_disagreement_and_calibration_denominators(self):
        packet,key,template=self.prepare()
        document=self.label(template)
        answer=document['reviews'][0]['answer_id']
        key['answers'][answer]['original_correct']=0
        single=audit.summarize(packet,key,[document])
        self.assertEqual(single['totals']['calibration_denominator'],1)
        self.assertEqual(single['totals']['judge_disagreements'],1)
        second=self.label(template,reviewer_id='human-2',correct=0)
        report=audit.summarize(packet,key,[document,second])
        self.assertEqual(report['totals']['reviewer_disagreements'],1)
        self.assertEqual(report['totals']['calibration_denominator'],0)
        self.assertIsNone(report['answers'][0]['human_correct'])

    def test_missing_judge_excluded_from_calibration(self):
        packet,key,template=self.prepare()
        document=self.label(template)
        key['answers'][document['reviews'][0]['answer_id']]['original_correct']=None
        report=audit.summarize(packet,key,[document])
        self.assertEqual(report['totals']['resolved_answers'],1)
        self.assertEqual(report['totals']['calibration_denominator'],0)

    def test_missing_trace_does_not_invent_failure_attribution(self):
        packet,key,template=self.prepare()
        report=audit.summarize(packet,key,[self.label(template,failure_stage='reranking')])
        row=report['answers'][0]['reviews'][0]
        self.assertEqual(row['failure_stage'],'unresolved')
        self.assertEqual(row['reported_failure_stage'],'reranking')

    def test_invalid_labels_rejected(self):
        packet,key,template=self.prepare()
        for values in [dict(correct=True),dict(correct=2),dict(reviewer_id=''),
                       dict(provenance='automated'),dict(reviewed_at='2026-11-03'),
                       dict(reference_ambiguity=None),dict(failure_stage='made_up')]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                audit.summarize(packet,key,[self.label(template,**values)])
        with self.assertRaises(ValueError):
            audit.summarize(packet,key,[self.label(template),self.label(template)])

    def test_identity_tampering_rejected(self):
        packet,key,template=self.prepare()
        packet['cases'][0]['question']='changed'
        with self.assertRaises(ValueError): audit.summarize(packet,key,[template])
        packet,key,template=self.prepare()
        template['packet_sha256']='other'
        with self.assertRaises(ValueError): audit.summarize(packet,key,[template])

    def test_duplicate_or_misaligned_cases_rejected(self):
        a,b,data=fixture()
        for variant in ('duplicate','question','dataset','history'):
            left,right,corpus=deepcopy((a,b,data))
            if variant=='duplicate': left['cases'].append(left['cases'][0])
            elif variant=='question': right['cases'][0]['question']='wrong'
            elif variant=='dataset': corpus[0]['qa'][0]['answer']='wrong'
            else: corpus[0]['conversation']['session_1'][0]['text']='Wrong history'
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                audit.prepare(left,right,corpus,dict(dataset='c'))

    def test_metadata_check_and_exclusive_output(self):
        warnings=audit.metadata_warnings('locomo-results(vector_reranker_k=50,10).json',
                    dict(config=dict(candidate_k=20,retrieval_k=10)))
        self.assertEqual([w['field'] for w in warnings],['candidate_k'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'packet.json'
            audit.write_new(path,dict(test=1))
            before=path.read_bytes()
            with self.assertRaises(FileExistsError): audit.write_new(path,dict(test=2))
            self.assertEqual(path.read_bytes(),before)

    def test_saved_reports_priority_union_and_source_preservation(self):
        root=Path(__file__).resolve().parents[1]
        paths=[root/'data/result'/n for n in ('locomo-results(vector_k=10).json','locomo-results(vector_reranker_k=50,10).json')]
        paths.append(root/'data/locomo/locomo10.json')
        loaded=[audit.read(p) for p in paths]
        hashes=dict(zip(('baseline','treatment','dataset'),[v[1] for v in loaded]))
        packet,key,labels=audit.prepare(*(v[0] for v in loaded),hashes)
        self.assertEqual(key['selection']['priority_questions'],35)
        self.assertEqual(key['selection']['reason_counts'],dict(gain=18,regression=1,unresolved_judgment=1,evidence_complete_failure=16))
        self.assertEqual([audit.read(p)[1] for p in paths],list(hashes.values()))
        self.assertEqual(audit.summarize(packet,key,[labels])['totals']['human_label_count'],0)
