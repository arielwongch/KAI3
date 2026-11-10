"""Synthetic offline custody/math tests, not model quality experiments."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
import Benchmark
import Compaction
import ExperimentRecording as R
from CompactionAnalysis import compaction_summary
from CompactionFidelity import prepare_review, score_review, calibrate
from CampaignAnalysis import compare_campaigns
from ResultAnalysis import enrich_report
from benchmark_helpers import FakeTokenizer
from test_binary_benchmark import judgment
from test_memory_integration import FakeOpenAIClient


def dataset():
    return [dict(sample_id=s, conversation={'session_1': [dict(speaker=s, dia_id=s+'1',
        text='I live in Rome and drink tea only on Sundays. '*8)]}, qa=[
        dict(question='Where?', answer='Rome', category=4, evidence=[s+'1']),
        dict(question='When?', answer='Sundays', category=3, evidence=[s+'1'])]) for s in ('A', 'B')]


def run_fixture(percent):
    job = Benchmark.BenchmarkJob(dataset(), dict(module='compaction', retain_percent=percent,
        question_limit=0, all_conversations=True))
    with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
         patch.object(Compaction, 'call_api', return_value=('Rome; tea on Sundays.', 0, 7)), \
         patch.object(Benchmark, 'client', FakeOpenAIClient('Rome')), \
         patch.object(Benchmark, 'judge_answer', return_value=(json.loads(judgment(1)), .01, 7)):
        job.run()
    if job.result['status'] != 'completed':
        raise AssertionError(job.result.get('error'))
    return job.snapshot()


def event(identity, before, after, **kwargs):
    return dict(event_id=identity, before_tokens=before, after_tokens=after,
        status=kwargs.pop('status', 'completed'), committed=kwargs.pop('committed', True),
        seconds=kwargs.pop('seconds', 2.), depth_after=kwargs.pop('depth_after', 1), attempts=[], **kwargs)


def summary_fixture(events, mode='one_shot'):
    memories = [dict(sample_id=str(i), module='compaction', formation_complete=True, error=None,
        memory={'compaction_events': [e]}, ingestion={'compaction_events': [deepcopy(e)]}) for i, e in enumerate(events)]
    return dict(config=dict(compaction_mode=mode, sample_ids=[str(i) for i in range(len(memories))]), memories=memories)


class RatioTests(unittest.TestCase):
    def test_ratio_of_sums_differs_from_inverse_mean(self):
        result = compaction_summary(summary_fixture([event('a', 100, 50), event('b', 900, 90)]))
        cohort = result['final_one_shot_cohort']
        self.assertTrue(cohort['cohort_complete'])
        self.assertAlmostEqual(cohort['aggregate_compression_factor'], 1000/140)
        self.assertEqual(cohort['weighted_retained_percent'], 14)
        self.assertEqual(cohort['mean_retained_percent'], 30)
        self.assertEqual(result['history']['unique_event_count'], 2)

    def test_noop_failure_and_repeated_scope(self):
        result = compaction_summary(summary_fixture([event('n', 100, 100, status='noop')]))
        self.assertEqual(result['final_one_shot_cohort']['aggregate_compression_factor'], 1)
        self.assertEqual(result['history']['noop_event_count'], 1)
        result = compaction_summary(summary_fixture([event('r', 100, 10)], 'repeated'))
        self.assertIsNone(result['final_one_shot_cohort']['aggregate_compression_factor'])
        self.assertEqual(result['operations']['aggregate_compression_factor'], 10)
        result = compaction_summary(summary_fixture([event('f', 100, 10, status='failed', committed=False)]))
        self.assertFalse(result['final_one_shot_cohort']['cohort_complete'])
        self.assertEqual(result['history']['uncommitted_event_count'], 1)

    def test_missing_empty_and_conflicting_events_not_silently_used(self):
        result = compaction_summary(summary_fixture([event('u', 100, None), event('v', 0, 0, status='noop')]))
        self.assertIsNone(result['operations']['weighted_retained_percent'])
        self.assertEqual(result['operations']['missing_or_empty_count'], 2)
        report = summary_fixture([event('duplicate', 100, 50)])
        other = deepcopy(report['memories'][0])
        other['memory']['compaction_events'][0]['after_tokens'] = 20
        report['previous_ingestions'] = [other]
        result = compaction_summary(report)
        self.assertEqual(result['history']['conflicting_event_ids'], ['duplicate'])
        self.assertIsNone(result['final_one_shot_cohort']['aggregate_compression_factor'])

    def test_latency_percentiles_disclose_missing_measurements(self):
        result = compaction_summary(summary_fixture([event('a', 100, 50, seconds=1),
            event('b', 100, 50, seconds=9), event('c', 100, 50, seconds=None)]))
        latency = result['history']['event_latency']
        self.assertEqual(latency['p50_seconds'], 5)
        self.assertAlmostEqual(latency['p95_seconds'], 8.6)
        self.assertEqual((latency['measured_count'], latency['total_count']), (2, 3))


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.left, cls.right = run_fixture(100), run_fixture(50)

    def propositions(self):
        return dict(version=1, dataset_hash=self.right['dataset_hash'], author='synthetic author', samples=[
            dict(sample_id=s, propositions=[
                dict(id='fact', text=s+' lives in Rome.', source_ids=[s+'1'], source_verified=True, kind='fact'),
                dict(id='condition', text=s+' drinks tea only on Sundays.', source_ids=[s+'1'], source_verified=True, kind='qualifier')])
            for s in ('A', 'B')])


class FidelityTests(FixtureTests):
    def test_source_window_exclusions_are_unavailable_not_lost(self):
        data = dataset()
        data[0]['conversation']['session_1'].insert(0, dict(speaker='A', dia_id='old', text='Earlier source.'))
        job = Benchmark.BenchmarkJob(data, dict(module='compaction', compaction_source_entries=1, retain_percent=100))
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(Benchmark, 'client', FakeOpenAIClient('Rome')), \
             patch.object(Benchmark, 'judge_answer', return_value=(json.loads(judgment(1)), .01, 7)):
            job.run()
        props = dict(version=1, dataset_hash=job.result['dataset_hash'], author='author', samples=[
            dict(sample_id='A', propositions=[dict(id='old', text='Earlier source.', source_ids=['old'], source_verified=True)])])
        review = prepare_review(job.result, props)
        self.assertEqual(review['items'], [])
        scored = score_review(job.result, review, dict(type='human', name='reviewer'))
        metrics = R.get(scored['recording'], scored['evaluation_artifact'])['metrics']
        self.assertEqual(metrics['excluded_proposition_count'], 1)
        self.assertIsNone(metrics['propositions']['proposition_recall'])
        self.assertIsNone(metrics['all_proposition_recall'])

    def test_exact_binding_roundtrip_labels_and_separate_metrics(self):
        report, before = deepcopy(self.right), deepcopy(self.right)
        review = prepare_review(report, self.propositions())
        manifest = R.get(review['recording'], review['manifest_artifact'])
        self.assertEqual(manifest['targets'][0]['output_text'], 'Rome; tea on Sundays.')
        for item in review['items']:
            item['label'] = 'preserved'
        scored = score_review(report, json.loads(json.dumps(review)), dict(type='human', name='reviewer'))
        R.validate(scored)
        metrics = R.get(scored['recording'], scored['evaluation_artifact'])['metrics']
        self.assertEqual(metrics['all_proposition_recall'], 1)
        self.assertEqual(metrics['by_kind']['qualifier']['proposition_recall'], 1)
        self.assertEqual(report, before)
        self.assertNotIn('all_proposition_recall', enrich_report(report)['comparison']['rows'][0]['overall'])

    def test_unknown_and_contradicted_have_explicit_denominators(self):
        review = prepare_review(self.right, self.propositions())
        review['items'][0]['label'], review['items'][1]['label'] = 'contradicted', 'uncertain'
        scored = score_review(self.right, review, dict(type='human', name='reviewer'))
        metrics = R.get(scored['recording'], scored['evaluation_artifact'])['metrics']
        self.assertIsNone(metrics['propositions']['proposition_recall'])
        self.assertEqual(metrics['propositions']['recall_bounds'], [0, .75])
        self.assertEqual(metrics['propositions']['unreviewed_count'], 2)
        self.assertIsNone(metrics['all_proposition_recall'])
        self.assertEqual(metrics['targets'][0]['all_propositions_preserved'], 0)

    def test_noop_and_invalid_source_propositions(self):
        review = prepare_review(self.left, self.propositions())
        target = R.get(review['recording'], review['manifest_artifact'])['targets'][0]
        self.assertEqual(target['status'], 'noop')
        self.assertEqual(target['source_text'], target['output_text'])
        for change in ('unverified', 'unknown_source', 'dataset'):
            props = self.propositions()
            if change == 'unverified':
                props['samples'][0]['propositions'][0]['source_verified'] = False
            elif change == 'unknown_source':
                props['samples'][0]['propositions'][0]['source_ids'] = ['future']
            else:
                props['dataset_hash'] = 'other'
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare_review(self.right, props)

    def test_tampering_duplicates_missing_artifacts_and_wrong_target(self):
        original = prepare_review(self.right, self.propositions())
        for change in ('text', 'duplicate', 'missing', 'invalid_label', 'different_target'):
            review = deepcopy(original)
            if change == 'text':
                review['recording']['artifacts'][review['manifest_artifact']['artifact_sha256']]['value']['targets'][0]['output_text'] = 'changed'
            elif change == 'duplicate':
                review['items'].append(deepcopy(review['items'][0]))
            elif change == 'missing':
                review['recording']['artifacts'].clear()
            elif change == 'invalid_label':
                review['items'][0]['label'] = 'true'
            else:
                review['items'][0]['target_id'] = 'other'
            with self.subTest(change=change), self.assertRaises(ValueError):
                score_review(self.right, review, dict(type='human', name='reviewer'))
        with self.assertRaisesRegex(ValueError, 'identity'):
            score_review(self.left, original, dict(type='human', name='reviewer'))

    def test_external_provenance_import_and_human_calibration(self):
        review = prepare_review(self.right, self.propositions())
        for item in review['items']:
            item['label'] = 'preserved'
        human = score_review(self.right, review, dict(type='human', name='human'))
        review['items'][0]['label'] = 'lost'
        provenance = dict(type='external_model', model='offline-model', requests=[dict(
            item_keys=[[i['target_id'], i['proposition_id']] for i in review['items']],
            request=dict(model='offline-model', messages=[dict(role='system', content='Judge archived evidence.')], temperature=0),
            response=dict(content='imported labels', usage=None))])
        model = score_review(self.right, review, provenance)
        evaluation = R.get(model['recording'], model['evaluation_artifact'])
        self.assertFalse(evaluation['evaluator']['requests'][0]['usage_complete'])
        R.validate(json.loads(json.dumps(model)))
        agreement = calibrate(human, model)
        self.assertEqual(agreement['exact_label_agreement'], .75)
        self.assertEqual(agreement['confusion_matrix']['preserved']['lost'], 1)
        provenance['requests'][0]['request']['api_key'] = 'must-not-archive'
        with self.assertRaises(ValueError):
            score_review(self.right, review, provenance)


class CampaignTests(FixtureTests):
    def test_questions_are_resampled_as_correlated_conversation_blocks(self):
        # Twenty identical questions per conversation make the sampling-unit
        # distinction observable: question resampling would give narrow bounds.
        reports = [deepcopy(self.left), deepcopy(self.right)]
        for side, report in enumerate(reports):
            data = R.get(report['recording'], report['dataset_artifact'], 'dataset')
            cases, manifest = [], []
            for sample in data:
                sample['qa'] = [deepcopy(sample['qa'][0]) for _ in range(20)]
                original = next(c for c in report['cases'] if c['sample_id'] == sample['sample_id'] and c['question_index'] == 0)
                for index in range(20):
                    case = deepcopy(original)
                    case.update(question_index=index, correct=int(side == 1 and sample['sample_id'] == 'A'))
                    cases.append(case)
                    manifest.append(dict(module='compaction', sample_id=sample['sample_id'], question_index=index, category=4))
            report['dataset_artifact'] = R.put(report['recording'], 'dataset', data)
            import hashlib
            report['dataset_hash'] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
            report.update(cases=cases, question_manifest=manifest)
        result = compare_campaigns([reports[0]], [reports[1]], resamples=1000)
        self.assertEqual(result['delta_percentage_points'], 50)
        self.assertEqual(result['confidence_interval_percentage_points'], [0, 100])
        self.assertEqual(result['conversation_count'], 2)
        self.assertEqual(result['question_count_per_repeat'], 40)

    def labelled(self, original, correct):
        report = deepcopy(original)
        for case in report['cases']:
            case['correct'] = correct
        return report

    def test_known_differences_negative_bounds_and_reproducibility(self):
        left, right = self.labelled(self.left, 0), self.labelled(self.right, 1)
        result = compare_campaigns([left], [right], resamples=200)
        self.assertEqual(result['delta_percentage_points'], 100)
        self.assertEqual(result['confidence_interval_percentage_points'], [100, 100])
        self.assertEqual(result, compare_campaigns([left], [right], resamples=200))
        reverse = compare_campaigns([right], [left], resamples=200)
        self.assertEqual(reverse['confidence_interval_percentage_points'], [-100, -100])
        right['cases'][1]['correct'] = 0
        a = compare_campaigns([left], [right], resamples=200, seed=8)
        self.assertEqual(a, compare_campaigns([left], [right], resamples=200, seed=8))
        self.assertEqual(a['delta_percentage_points'], 75)

    def test_unjudged_and_missing_cases_are_operational_failures(self):
        left, right = deepcopy(self.left), deepcopy(self.right)
        right['cases'].pop()
        right['cases'][0]['correct'] = None
        result = compare_campaigns([left], [right], resamples=100)
        self.assertEqual(result['right']['end_to_end_success_percent'], 50)
        self.assertEqual(result['right']['judged_accuracy_percent'], 100)
        self.assertEqual(result['right']['unjudged_count'], 2)
        self.assertEqual(result['delta_percentage_points'], -50)

    def test_one_conversation_has_no_informative_interval(self):
        reports = [deepcopy(self.left), deepcopy(self.right)]
        for report in reports:
            report['config']['sample_ids'] = ['A']
            for field in ('cases', 'memories', 'question_manifest'):
                report[field] = [i for i in report[field] if str(i['sample_id']) == 'A']
        result = compare_campaigns([reports[0]], [reports[1]], resamples=100)
        self.assertIsNone(result['confidence_interval_percentage_points'])
        self.assertIn('fewer than two', result['interval_status'])

    def test_mismatched_cohorts_controls_and_corruption_rejected(self):
        for mismatch in ('question', 'tokenizer', 'prompt', 'config', 'code', 'source', 'archive', 'legacy'):
            right = deepcopy(self.right)
            if mismatch == 'question':
                right['question_manifest'], right['cases'] = right['question_manifest'][:-1], right['cases'][:-1]
            elif mismatch == 'tokenizer':
                right['tokenizer'] = {'id': 'other'}
            elif mismatch == 'prompt':
                right['answer_prompt_hash'] = 'other'
            elif mismatch == 'config':
                right['config']['memory_context_tokens'] = 40000
            elif mismatch == 'code':
                right['code_identity']['source_sha256'] = 'other'
            elif mismatch == 'source':
                right['memories'][0]['source_artifact'] = R.put(right['recording'], 'ordered-source', ['other'])
            elif mismatch == 'archive':
                right['recording']['artifacts'].clear()
            else:
                right = {'cases': [], 'config': {}}
            with self.subTest(mismatch=mismatch), self.assertRaises(ValueError):
                compare_campaigns([self.left], [right], resamples=100)

    def test_repeat_pairing_and_reused_construction_rejection(self):
        left2, right2 = deepcopy(self.left), deepcopy(self.right)
        for report in (left2, right2):
            report['run_id'], report['compaction_campaign'] = str(uuid4()), dict(repeat=2)
            for memory in report['memories']:
                memory['ingestion']['construction_id'] = str(uuid4())
        result = compare_campaigns([self.left, left2], [self.right, right2], resamples=100)
        self.assertEqual(result['repeat_ids'], [1, 2])
        self.assertEqual(result['left']['selected_count'], 8)
        with self.assertRaisesRegex(ValueError, 'repeat IDs'):
            compare_campaigns([self.left, left2], [self.right], resamples=100)
        right2['memories'][0]['ingestion']['construction_id'] = self.right['memories'][0]['ingestion']['construction_id']
        with self.assertRaisesRegex(ValueError, 'reuse'):
            compare_campaigns([self.left, left2], [self.right, right2], resamples=100)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            compare_campaigns([self.left, self.left], [self.right], resamples=100)

    def test_invalid_bootstrap_controls(self):
        for controls in ({'vary': []}, {'vary': ['seed']}, {'resamples': True}, {'resamples': 0},
                         {'seed': True}, {'confidence': float('nan')}, {'confidence': 1}):
            with self.subTest(controls=controls), self.assertRaises(ValueError):
                compare_campaigns([self.left], [self.right], **controls)


class CLITests(FixtureTests):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, 'tools/compaction_evaluate.py', *map(str, args)],
                              capture_output=True, text=True, timeout=30)

    def test_portable_prepare_score_compare_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right, props = root/'left.json', root/'right.json', root/'propositions.json'
            for path, value in ((left, self.left), (right, self.right), (props, self.propositions())):
                path.write_text(json.dumps(value), encoding='utf-8')
            review, scored, comparison = root/'review.json', root/'scored.json', root/'comparison.json'
            result = self.run_cli('prepare', '--report', right, '--propositions', props, '--output', review)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(review.read_text(encoding='utf-8'))
            for item in data['items']:
                item['label'] = 'preserved'
            review.write_text(json.dumps(data), encoding='utf-8')
            result = self.run_cli('score', '--report', right, '--review', review, '--annotator', 'human', '--output', scored)
            self.assertEqual(result.returncode, 0, result.stderr)
            R.validate(json.loads(scored.read_text(encoding='utf-8')))
            result = self.run_cli('compare', '--left', left, '--right', right, '--resamples', 100, '--output', comparison)
            self.assertEqual(result.returncode, 0, result.stderr)
            original = comparison.read_bytes()
            result = self.run_cli('compare', '--left', left, '--right', right, '--output', comparison)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(comparison.read_bytes(), original)
            self.assertEqual(json.loads(right.read_text(encoding='utf-8')), self.right)


if __name__ == '__main__':
    unittest.main()
