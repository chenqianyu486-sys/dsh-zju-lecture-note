"""Run the real Node/Python timeout and child-generation regressions."""

import os
import subprocess
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBridgeTimeoutRecovery(unittest.TestCase):
    def test_timeout_and_stale_process_events(self):
        result = subprocess.run(
            ["node", "tests/bridge_timeout_recovery.mjs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
