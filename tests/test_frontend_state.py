"""Run the DOM-free frontend regressions with the same Node runtime as CI."""
from pathlib import Path
import shutil
import subprocess
import unittest


class FrontendStateTests(unittest.TestCase):
    def test_frontend_state_and_resume(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Install Node.js 22+ to run frontend regressions (required in CI).')
        result = subprocess.run(
            [node, '--test', 'tests/test_frontend_state.js'],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
