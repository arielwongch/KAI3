import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import app

class ResultLibraryTests(unittest.TestCase):
    def test_nested_listing_loading_and_path_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'results';root.mkdir()
            (root/'experiment').mkdir()
            (root/'experiment'/'report.json').write_text('{"cases":[],"scores":[]}',encoding='utf-8')
            (root/'bad.json').write_text('broken',encoding='utf-8')
            (root/'dataset.json').write_text('[]',encoding='utf-8')
            (Path(directory)/'outside.json').write_text('{"cases":[]}',encoding='utf-8')
            with patch.object(app,'RESULT_LIBRARY',root):
                client=app.app.test_client()
                self.assertIn('experiment/report.json',client.get('/api/results').json['files'])
                self.assertEqual(client.get('/api/results/file',query_string={'path':'experiment/report.json'}).json['report']['cases'],[])
                self.assertEqual(client.get('/api/results/file',query_string={'path':'../outside.json'}).status_code,404)
                self.assertEqual(client.get('/api/results/file',query_string={'path':'bad.json'}).status_code,400)
                self.assertEqual(client.get('/api/results/file',query_string={'path':'dataset.json'}).status_code,400)
                (root/'new.json').write_text('{"cases":[]}',encoding='utf-8')
                self.assertIn('new.json',client.get('/api/results').json['files'])

if __name__=='__main__':
    unittest.main()
