"""Run the DOM-stubbed importer tests when Node.js is available."""
from pathlib import Path
import shutil
import subprocess
import unittest

class ResultImportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for result import UI tests')
    def test_local_import_validation_and_rendering(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', 'tests/test_result_import.js'], cwd=root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == '__main__':
    unittest.main()
