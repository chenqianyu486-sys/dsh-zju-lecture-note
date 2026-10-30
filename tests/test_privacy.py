#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Privacy-scan regression tests.

The scanner is the mechanical guarantee behind "no cookie / personal data in
this repository", so it needs its own tests: it must catch a planted secret
and it must report the real repository as clean.
"""

import io
import os
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import privacy_scan  # noqa: E402


class TestScanner(unittest.TestCase):

    def test_repository_working_tree_is_clean(self):
        findings = privacy_scan.scan_files(ROOT)
        self.assertEqual(findings, [], "\n".join(f"{f.location}: {f.excerpt}" for f in findings))

    def test_gitignore_covers_private_material(self):
        self.assertEqual(privacy_scan.check_gitignore(ROOT), [])

    def test_detects_api_key(self):
        text = 'API_KEY = "sk-' + "A" * 32 + '"'
        rules = {finding.rule for finding in privacy_scan.scan_text(text, "test", "x.py")}
        self.assertIn("openai-key", rules)

    def test_detects_windows_user_path(self):
        text = 'default = "' + "C:/Users/" + "alice/project" + '"'
        rules = {finding.rule for finding in privacy_scan.scan_text(text, "test", "x.py")}
        self.assertIn("windows-user-path", rules)

    def test_detects_macos_user_path(self):
        text = 'path = "' + "/Users/" + "alice/project" + '"'
        rules = {finding.rule for finding in privacy_scan.scan_text(text, "test", "x.py")}
        self.assertIn("posix-user-path", rules)

    def test_detects_cookie_assignment(self):
        text = "SESS" + "DATA=" + "9f8e7d6c5b4a39281706f5e4d3c2b1a0"
        rules = {finding.rule for finding in privacy_scan.scan_text(text, "test", "x.py")}
        self.assertIn("cookie-assignment", rules)

    def test_detects_private_key(self):
        text = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
        rules = {finding.rule for finding in privacy_scan.scan_text(text, "test", "x")}
        self.assertIn("private-key", rules)

    def test_allows_documented_placeholders(self):
        for line in (
            'path = "C:/Users/me/project"',
            'path = "C:/Users/<your-name>/project"',
            'path = "/home/me/project"',
            'url = "https://example.com/callback"',
            'SESSDATA=top-secret-value',
        ):
            findings = privacy_scan.scan_text(line, "test", "README.md")
            self.assertEqual(findings, [], line)

    def test_tarball_scan_finds_a_planted_secret(self):
        directory = tempfile.mkdtemp(prefix="privacy-tarball-")
        tarball = os.path.join(directory, "package.tgz")
        try:
            with tarfile.open(tarball, "w:gz") as archive:
                payload = b'TOKEN = "ghp_' + b"B" * 30 + b'"\n'
                info = tarfile.TarInfo("package/lib/leak.js")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            findings = privacy_scan.scan_tarball(tarball)
            self.assertTrue(findings)
            self.assertEqual(findings[0].rule, "github-token")
        finally:
            import shutil
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
