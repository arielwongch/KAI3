"""Context size and provider-token cost are separate measurements."""
from copy import deepcopy
from types import SimpleNamespace
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, 'src')
import ResultAnalysis as analysis


class ContextMetricTests(unittest.TestCase):
    def fixture(self):
        return dict(cases=[
            dict(module='vector_store', sample_id='one', category=2,
                 diagnostics=dict(memory_context_tokens=100, answer_tokens=10, prompt_tokens=9999)),
            dict(module='vector_store', sample_id='one', category=4,
                 diagnostics=dict(memory_context_tokens=300, answer_tokens=20))],
            memories=[dict(module='vector_store', sample_id='one', ingestion=dict(memory_tokens=10))])

    def test_context_and_cost_have_independent_totals_and_category_means(self):
        source = self.fixture()
        before = deepcopy(source)
        row = analysis.enrich_report(source)['comparison']['rows'][0]
        self.assertEqual(row['overall']['mean_context_tokens'], 200)
        self.assertEqual(row['overall']['total_context_tokens'], 400)
        self.assertEqual(row['overall']['context_token_count'], 2)
        self.assertEqual(row['overall']['mean_question_tokens'], 20)
        self.assertEqual(row['categories']['2']['mean_context_tokens'], 100)
        self.assertEqual(row['categories']['4']['mean_context_tokens'], 300)
        self.assertEqual(source, before)

    def test_empty_context_is_zero_and_missing_is_unknown(self):
        with patch.object(analysis, '_count_context') as count:
            self.assertEqual(analysis.context_tokens(dict(supplied_context='')), 0)
            self.assertIsNone(analysis.context_tokens(dict(prompt_tokens=9999)))
            count.assert_not_called()
        source = self.fixture()
        source['cases'][1]['diagnostics'] = {}
        metrics = analysis.enrich_report(source)['comparison']['rows'][0]['overall']
        self.assertIsNone(metrics['mean_context_tokens'])
        self.assertEqual(metrics['context_token_count'], 1)

    def test_explicit_invalid_counts_do_not_fall_back_to_prompt_usage(self):
        for value in (None, -1, True, 1.5, '100'):
            with self.subTest(value=value), patch.object(analysis, '_count_context') as count:
                self.assertIsNone(analysis.context_tokens(dict(memory_context_tokens=value, supplied_context='text', prompt_tokens=100)))
                count.assert_not_called()

    def test_legacy_saved_context_is_counted_without_question_or_instruction_text(self):
        source = self.fixture()
        for case in source['cases']:
            case['diagnostics'].pop('memory_context_tokens')
            case['diagnostics']['supplied_context'] = 'Alice lives in Rome.'
            case['question'] = 'An unrelated long question.'
        with patch.object(analysis, '_count_context', return_value=5) as count:
            metrics = analysis.enrich_report(source)['comparison']['rows'][0]['overall']
        self.assertEqual(metrics['mean_context_tokens'], 5)
        count.assert_called_once_with('Alice lives in Rome.')
        self.assertNotIn('memory_context_tokens', source['cases'][0]['diagnostics'])

    def test_offline_tokenizer_disables_padding_and_truncation(self):
        analysis._context_tokenizer.cache_clear()
        self.addCleanup(analysis._context_tokenizer.cache_clear)
        tokenizer = Mock()
        with patch('huggingface_hub.try_to_load_from_cache', return_value='local-tokenizer.json'), patch('tokenizers.Tokenizer.from_file', return_value=tokenizer):
            self.assertIs(analysis._context_tokenizer(), tokenizer)
        tokenizer.no_padding.assert_called_once_with()
        tokenizer.no_truncation.assert_called_once_with()

    def test_no_cached_tokenizer_leaves_legacy_counts_unknown(self):
        with patch.object(analysis, '_context_tokenizer', return_value=None):
            self.assertIsNone(analysis.context_tokens(dict(supplied_context='Not cached.')))

    def test_corrupt_cached_tokenizer_leaves_report_context_unknown(self):
        analysis._context_tokenizer.cache_clear()
        self.addCleanup(analysis._context_tokenizer.cache_clear)
        source = self.fixture()
        for case in source['cases']:
            case['diagnostics'].pop('memory_context_tokens')
            case['diagnostics']['supplied_context'] = 'Alice lives in Rome.'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tokenizer.json'
            path.write_text('{broken', encoding='utf-8')
            with patch('huggingface_hub.try_to_load_from_cache', return_value=str(path)):
                metrics = analysis.enrich_report(source)['comparison']['rows'][0]['overall']
        self.assertIsNone(metrics['mean_context_tokens'])
        self.assertEqual(metrics['context_token_count'], 0)
        self.assertEqual(metrics['mean_question_tokens'], 20)

    def test_large_report_counts_each_distinct_context_once_per_enrichment(self):
        source = dict(cases=[dict(module='question_only', category=4,
            diagnostics=dict(supplied_context=f'context-{i}', answer_tokens=0))
            for i in range(1200)])
        source['cases'].append(deepcopy(source['cases'][0]))
        tokenizer = Mock()
        tokenizer.encode.return_value = SimpleNamespace(ids=[1, 2, 3])
        with patch.object(analysis, '_context_tokenizer', return_value=tokenizer):
            for _ in range(2):
                tokenizer.encode.reset_mock()
                row = analysis.enrich_report(source)['comparison']['rows'][0]
                self.assertEqual(tokenizer.encode.call_count, 1200)
                self.assertEqual(row['overall']['mean_context_tokens'], 3)
                self.assertEqual(row['categories']['4']['total_context_tokens'], 3603)

    def test_recorded_counts_take_precedence_over_shared_context_cache(self):
        source = self.fixture()
        source['cases'][0]['diagnostics'].pop('memory_context_tokens')
        for case in source['cases']:
            case['diagnostics']['supplied_context'] = 'Shared context.'
        with patch.object(analysis, '_count_context', return_value=5) as count:
            row = analysis.enrich_report(source)['comparison']['rows'][0]
        count.assert_called_once_with('Shared context.')
        self.assertEqual(row['overall']['total_context_tokens'], 305)
        self.assertEqual(row['categories']['4']['mean_context_tokens'], 300)

    def test_saved_run_analysis_enriches_completed_views_without_changing_export(self):
        os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
        import app
        source = self.fixture()
        source['status'] = 'completed'
        job = SimpleNamespace(snapshot=lambda: deepcopy(source))
        with patch.object(app, 'jobs', {'context-run': job}), patch.object(app, 'refresh_jobs'):
            client = app.app.test_client()
            report = client.get('/api/benchmarks/context-run?analysis=1').json
            self.assertEqual(report['comparison']['rows'][0]['overall']['mean_context_tokens'], 200)
            self.assertEqual(client.get('/api/benchmarks/context-run/export').json, source)
            source['status'] = 'running'
            self.assertNotIn('comparison', client.get('/api/benchmarks/context-run?analysis=1').json)


if __name__ == '__main__':
    unittest.main()
