"""Run real Node/Python regressions for workspace capacity."""
import os
import subprocess
import unittest


class TestBridgeWorkspaceCapacity(unittest.TestCase):
    def test_busy_workspaces_are_not_evicted(self):
        result = subprocess.run(
            ["node", "tests/bridge_workspace_capacity.mjs"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
