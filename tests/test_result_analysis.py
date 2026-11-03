"""Offline import, derivation, and persistence regressions."""
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
from ResultAnalysis import enrich_report


class AnalysisTests(unittest.TestCase):
    def fixture(self):
        return dict(cases=[dict(module='vector_store', category=2, correct=1,
                               diagnostics=dict(prompt_tokens=20, completion_tokens=5, judge_tokens=10, total_seconds=2)),
                          dict(module='vector_store', category=2, correct=None, diagnostics={})],
                    question_manifest=[dict(module='vector_store', category=2)]*3,
                    memories=[dict(module='vector_store', memory=dict(entries=[dict(text='你好')]))])

    def test_derivation_missing_coverage_and_preservation(self):
        original = self.fixture()
        report = enrich_report(original)
        self.assertNotIn('answer_tokens', original['cases'][0]['diagnostics'])
        self.assertEqual(report['cases'][0]['diagnostics']['answer_tokens'], 25)
        self.assertNotIn('answer_tokens', report['cases'][1]['diagnostics'])
        metrics = report['comparison']['rows'][0]['overall']
        self.assertEqual(metrics['accuracy_percent'], 100)
        self.assertAlmostEqual(metrics['completion_percent'], 100/3)
        self.assertIsNone(metrics['mean_question_tokens'])
        self.assertEqual(metrics['token_count'], 0)
        self.assertIsNone(metrics['total_question_tokens'])
        self.assertEqual(metrics['stored_text_bytes'], 6)
        self.assertEqual(enrich_report(report), report)
        original['cases'][0]['diagnostics']['answer_tokens'] = 99
        self.assertEqual(enrich_report(original)['cases'][0]['diagnostics']['answer_tokens'], 99)

    def test_unknown_is_not_zero_and_modules_are_separate(self):
        report = enrich_report(dict(cases=[dict(module='a', category=1),dict(module='b', category=4, correct=0)]))
        a, b = report['comparison']['rows']
        self.assertIsNone(a['overall']['accuracy_percent'])
        self.assertIsNone(a['overall']['stored_text_bytes'])
        self.assertEqual(b['overall']['accuracy_percent'], 0)
        self.assertNotIn('1', b['categories'])

    def test_invalid_structures(self):
        for report in ([], {'cases':[None]}, {'cases':[], 'memories':[{'memory':None}]}, {'cases':[], 'question_manifest':[0]}):
            with self.subTest(report=report), self.assertRaises(ValueError):
                enrich_report(report)

    def test_bundled_exports(self):
        for file in Path('data/result').glob('*.json'):
            with self.subTest(file=file):
                report = enrich_report(json.loads(file.read_text(encoding='utf-8-sig')))
                self.assertTrue(report['comparison']['rows'])
                for row in report['comparison']['rows']:
                    accuracy = row['overall']['accuracy_percent']
                    self.assertTrue(accuracy is None or 0 <= accuracy <= 100)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required')
    def test_comparison_ui(self):
        result = subprocess.run(['node', 'tests/test_compare_ui.js'], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_upload_persist_reload_download_and_boundary(self):
        import app
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RESULT_LIBRARY', Path(directory)):
            client = app.app.test_client()
            def upload(value, name='report.json', action='ask'):
                return client.post('/api/results/import', data={'file':(io.BytesIO(json.dumps(value).encode()), name), 'action':action})
            first = upload(self.fixture())
            self.assertEqual(first.status_code, 201)
            name = first.json['path']
            saved = json.loads((Path(directory)/name).read_text(encoding='utf-8'))
            self.assertEqual(saved, first.json['report'])
            self.assertNotEqual(upload(self.fixture(), action='duplicate').json['path'], name)
            self.assertEqual(client.get('/api/results/file', query_string={'path':name,'analysis':'1'}).json['report'], saved)
            download = client.get('/api/results/file',query_string={'path':name,'download':'1'})
            self.assertIn('attachment', download.headers['Content-Disposition'])
            download.close()
            self.assertEqual(client.post('/api/results/enrich', json={'path':name}).status_code, 200)
            self.assertEqual(client.post('/api/results/enrich', json={'path':'../outside.json'}).status_code, 404)
            self.assertEqual(upload([]).status_code, 400)
            self.assertEqual(client.get('/compare').status_code, 200)
            asset = client.get('/compare.js')
            self.assertEqual(asset.status_code, 200)
            asset.close()

    def test_original_names_individual_downloads_and_deletion(self):
        import app
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RESULT_LIBRARY', Path(directory)):
            root = Path(directory)
            client = app.app.test_client()
            original = 'Results (vector_k=10) 測試.JSON'
            def upload(name=original, action='ask'):
                response = client.post('/api/results/import', data={
                    'file': (io.BytesIO(json.dumps(self.fixture()).encode()), name), 'action':action})
                self.assertEqual(response.status_code, 201)
                return response.json['path']
            first, second = upload(), upload(action='duplicate')
            self.assertNotEqual(first, second)
            self.assertEqual(first, original)
            self.assertEqual(Path(first).name, original)
            self.assertEqual(Path(second).name, 'Results (vector_k=10) 測試 (1).JSON')
            self.assertIn(first, client.get('/api/results').json['files'])
            downloaded = client.get('/api/results/file', query_string={'path':first, 'download':'1'})
            self.assertIn(original, unquote(downloaded.headers['Content-Disposition']))
            downloaded.close()
            (root/'unselected.json').write_text('{"cases":[]}', encoding='utf-8')
            for name in (first, second):
                downloaded = client.get('/api/results/file', query_string={'path':name, 'download':'1'})
                self.assertEqual(downloaded.status_code, 200)
                self.assertEqual(downloaded.mimetype, 'application/json')
                self.assertEqual(json.loads(downloaded.data), json.loads((root/name).read_text(encoding='utf-8')))
                downloaded.close()
            self.assertIn(client.post('/api/results/download', json={'paths':[first,second]}).status_code, (404,405))
            for path in ('../outside.json', 'missing.json', 'uploads/../../outside.json'):
                self.assertEqual(client.delete('/api/results/file', query_string={'path':path}).status_code, 404)
            # Downloading selected files does not mutate any library content.
            self.assertTrue((root/'unselected.json').is_file())
            with patch.object(Path, 'unlink', side_effect=OSError('locked')):
                self.assertEqual(client.delete('/api/results/file', query_string={'path':first}).status_code, 503)
            self.assertTrue((root/first).is_file())
            self.assertEqual(client.delete('/api/results/file', query_string={'path':first}).status_code, 200)
            self.assertFalse((root/first).exists())
            self.assertTrue((root/second).exists())
            self.assertNotIn(first, client.get('/api/results').json['files'])
            self.assertEqual(client.delete('/api/results/file', query_string={'path':first}).status_code, 404)

    def test_legacy_upload_names_and_uniform_file_management(self):
        import app
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RESULT_LIBRARY', Path(directory)):
            root = Path(directory)
            names = ['uploads/'+'a'*32+'-report.json', 'uploads/new/report.json', 'report (2).json']
            for name in names:
                (root/name).parent.mkdir(parents=True, exist_ok=True)
                (root/name).write_text('{"cases":[]}', encoding='utf-8')
            client = app.app.test_client()
            downloaded = client.get('/api/results/file', query_string={'path':names[0], 'download':'1'})
            self.assertIn('filename=report.json', downloaded.headers['Content-Disposition'])
            downloaded.close()
            renamed = client.post('/api/results/rename', json={'path':names[0], 'name':'renamed (1).json'})
            self.assertEqual(renamed.status_code, 200)
            self.assertEqual(renamed.json['path'], 'uploads/renamed (1).json')
            self.assertTrue((root/renamed.json['path']).is_file())
            self.assertEqual(client.delete('/api/results/file', query_string={'path':renamed.json['path']}).status_code, 200)
            self.assertEqual(client.delete('/api/results/file', query_string={'path':names[2]}).status_code, 200)

    def test_duplicate_choices_numbering_and_replacement(self):
        import app
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RESULT_LIBRARY', Path(directory)):
            root = Path(directory)
            client = app.app.test_client()
            original = 'Results (vector_k=10) 測試.JSON'
            def upload(action='ask', path=None, report=None, name=original):
                data = {'file':(io.BytesIO(json.dumps(self.fixture() if report is None else report).encode()), name), 'action':action}
                if path is not None:
                    data['replace_path'] = path
                return client.post('/api/results/import', data=data)
            first = upload().json['path']
            before = (root/first).read_bytes()
            conflict = upload()
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json['conflicts'], [first])
            self.assertEqual(conflict.json['duplicate_name'], 'Results (vector_k=10) 測試 (1).JSON')
            self.assertEqual(client.get('/api/results').json['files'], [first])
            self.assertEqual((root/first).read_bytes(), before)
            for index in (1, 2):
                duplicate = upload('duplicate')
                self.assertEqual(duplicate.status_code, 201)
                self.assertEqual(Path(duplicate.json['path']).name, f'Results (vector_k=10) 測試 ({index}).JSON')
            self.assertEqual(upload(name=original.lower()).status_code, 409)
            files = client.get('/api/results').json['files']
            replacement = self.fixture()
            replacement['status'] = 'replaced-test'
            replaced = upload('replace', first, replacement)
            self.assertEqual(replaced.status_code, 200)
            self.assertEqual(replaced.json['path'], first)
            self.assertTrue(replaced.json['replaced'])
            self.assertEqual(json.loads((root/first).read_text(encoding='utf-8'))['status'], 'replaced-test')
            self.assertEqual(client.get('/api/results').json['files'], files)
            different_name = next(path for path in files if Path(path).stem.endswith('(1)'))
            for path in (None, '../outside.json', different_name):
                # A replacement must target an existing matching basename.
                self.assertEqual(upload('replace', path).status_code, 409)
            self.assertEqual(upload('replace', first, report=[]).status_code, 400)
            with patch.object(app, 'atomic_json', side_effect=OSError('locked')):
                self.assertEqual(upload('replace', first).status_code, 503)
            self.assertEqual(json.loads((root/first).read_text(encoding='utf-8'))['status'], 'replaced-test')
            self.assertEqual(upload('unsupported').status_code, 400)
            # A numeric suffix must not bypass the filename byte limit.
            long_name = 'x'*195+'.json'
            original_bytes = b'{"cases":[]}'
            (root/long_name).write_bytes(original_bytes)
            self.assertEqual(upload('duplicate', name=long_name).status_code, 400)
            self.assertEqual((root/long_name).read_bytes(), original_bytes)
            self.assertFalse((root/('x'*195+' (1).json')).exists())

    def test_duplicate_detection_for_saved_and_legacy_files(self):
        import app
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RESULT_LIBRARY', Path(directory)):
            root = Path(directory)
            names = ['report.json', 'uploads/'+'a'*32+'-report.json', 'uploads/new/report (1).json']
            for name in names:
                (root/name).parent.mkdir(parents=True, exist_ok=True)
                (root/name).write_text('{"cases":[]}', encoding='utf-8')
            client = app.app.test_client()
            def upload(action='ask', target=None):
                return client.post('/api/results/import', data={'file':(io.BytesIO(b'{"cases":[],"status":"new"}'), 'report.json'),
                    'action':action, 'replace_path':target or ''})
            conflict = upload()
            self.assertEqual(conflict.status_code, 409)
            self.assertCountEqual(conflict.json['conflicts'], names[:2])
            self.assertEqual(conflict.json['duplicate_name'], 'report (2).json')
            replaced = upload('replace', names[1])
            self.assertEqual(replaced.status_code, 200)
            self.assertEqual(json.loads((root/names[1]).read_text(encoding='utf-8'))['status'], 'new')
            self.assertNotIn('status', json.loads((root/names[0]).read_text(encoding='utf-8')))
            self.assertEqual(upload('replace', names[0]).status_code, 200)
            # If a previously prompted target is gone, do not recreate it.
            (root/names[1]).unlink()
            retry = upload('replace', names[1])
            self.assertEqual(retry.status_code, 409)
            self.assertFalse((root/names[1]).exists())


if __name__ == '__main__':
    unittest.main()
