import os
import io
import json
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import app

class ResultLibraryTests(unittest.TestCase):
    def test_filename_sort_rename_conflicts_and_failures(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RESULT_LIBRARY', Path(directory)):
            root = Path(directory)
            for name in ('z.json', 'uploads/2/Beta.json', 'Alpha.json', 'run10.json', 'uploads/1/run2.json'):
                (root/name).parent.mkdir(parents=True, exist_ok=True)
                (root/name).write_text('{"cases":[],"status":"preserve"}', encoding='utf-8')
            client = app.app.test_client()
            self.assertEqual(client.get('/api/results').json['files'], ['Alpha.json','uploads/2/Beta.json','uploads/1/run2.json','run10.json','z.json'])
            before = (root/'z.json').read_bytes()
            response = client.post('/api/results/rename', json={'path':'z.json','name':'A (trial) 測試.json'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['path'], 'A (trial) 測試.json')
            self.assertEqual((root/response.json['path']).read_bytes(), before)
            self.assertFalse((root/'z.json').exists())
            for name in ('alpha.json', 'BETA.json'):
                self.assertEqual(client.post('/api/results/rename', json={'path':response.json['path'],'name':name}).status_code, 409)
            self.assertEqual(client.post('/api/results/rename', json={'path':response.json['path'],'name':response.json['path']}).status_code, 200)
            with patch.object(Path,'rename',side_effect=OSError('locked')):
                self.assertEqual(client.post('/api/results/rename',json={'path':response.json['path'],'name':'other.json'}).status_code,503)
            self.assertEqual((root/response.json['path']).read_bytes(), before)
            self.assertEqual(client.delete('/api/results/file',query_string={'path':'Alpha.json'}).status_code,200)
            self.assertFalse((root/'Alpha.json').exists())

    def test_all_library_operations_reject_outside_paths_and_unsafe_names(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'results';root.mkdir()
            outside=base/'outside.json';outside.write_text('{"cases":[],"secret":"outside"}',encoding='utf-8')
            original=b'{"cases":[],"status":"inside"}'
            (root/'inside.json').write_bytes(original)
            with patch.object(app,'RESULT_LIBRARY',root):
                client=app.app.test_client()
                for path in ('../outside.json', str(outside), '/outside.json', r'C:\outside.json', r'..\outside.json', 'nested/../../outside.json', './inside.json', 'nested//inside.json', 'inside.json:secret', 'bad\x00.json'):
                    with self.subTest(path=path):
                        for query in ({'path':path},{'path':path,'download':'1'},{'path':path,'analysis':'1'}):
                            self.assertEqual(client.get('/api/results/file',query_string=query).status_code,404)
                        self.assertEqual(client.delete('/api/results/file',query_string={'path':path}).status_code,404)
                        self.assertEqual(client.post('/api/results/enrich',json={'path':path}).status_code,404)
                        self.assertEqual(client.post('/api/results/rename',json={'path':path,'name':'safe.json'}).status_code,404)
                for name in ('../outside.json', '/outside.json', r'C:\outside.json', 'nested/new.json', r'nested\new.json', 'bad:stream.json', 'CON.json', 'bad?.json', 'bad\n.json', 'x'*201+'.json', 'file.txt'):
                    with self.subTest(name=name):
                        self.assertEqual(client.post('/api/results/rename',json={'path':'inside.json','name':name}).status_code,400)
                        # Multipart quoted-string escaping must preserve the
                        # literal backslashes we are testing at the server.
                        response=client.post('/api/results/import',data={'file':(io.BytesIO(original),name.replace('\\','\\\\'))})
                        self.assertEqual(response.status_code,400)
                self.assertEqual((root/'inside.json').read_bytes(),original)
                self.assertEqual(client.post('/api/results/rename',json={'path':'inside.json','name':'bad\ud800.json'}).status_code,400)
                self.assertEqual(json.loads(outside.read_text())['secret'],'outside')
                self.assertFalse((base/'safe.json').exists())

    @unittest.skipUnless(os.name=='nt','Windows junction test')
    def test_windows_junction_cannot_expose_or_modify_another_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'results';root.mkdir();outside=base/'private';outside.mkdir()
            original=b'{"cases":[],"secret":"unchanged"}';(outside/'private.json').write_bytes(original)
            link=root/'linked'
            result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            try:
                with patch.object(app,'RESULT_LIBRARY',root):
                    client=app.app.test_client()
                    self.assertEqual(client.get('/api/results').json['files'],[])
                    for operation in ('read','download','delete','enrich','rename'):
                        if operation in ('read','download'):
                            response=client.get('/api/results/file',query_string={'path':'linked/private.json','download':'1' if operation=='download' else '0'})
                        elif operation=='delete':
                            response=client.delete('/api/results/file',query_string={'path':'linked/private.json'})
                        else:
                            response=client.post('/api/results/'+operation,json={'path':'linked/private.json','name':'changed.json'})
                        self.assertEqual(response.status_code,404)
                    self.assertEqual((outside/'private.json').read_bytes(),original)
                    self.assertFalse((outside/'changed.json').exists())
            finally:
                link.rmdir()

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
