#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""隐私扫描器掩码（安全审查 P1-2 / 7.5）。

扫描器的职责是**发现**秘密，不是把它再打印一遍。旧实现只截断不掩码，
文本与 JSON 输出都包含命中的原始行，命中真实密钥时会把密钥写进终端 /
CI 日志。现在默认只输出 path:line、规则名与命中长度；``--show-excerpt``
才输出前后各 6 字符、中间 ``***`` 的掩码摘录。
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import privacy_scan  # noqa: E402

# 拼出来，避免 scanners 把测试文件本身当成泄露。
SECRET = "sk-" + "Q7mZ2pLx9VbN4cR8tY6uW1sE5dF3gH0jK"
LINE = 'API_KEY = "' + SECRET + '"'


def capture_report(findings, *, as_json=False, show_excerpt=False):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        privacy_scan.report(
            findings, [], as_json=as_json, show_excerpt=show_excerpt
        )
    return stream.getvalue()


class TestFindingMetadata(unittest.TestCase):

    def setUp(self):
        self.findings = privacy_scan.scan_text(LINE, "test", "config.py")
        self.assertTrue(self.findings, "测试样本没有被 openai-key 规则命中")

    def test_finding_records_the_matched_length(self):
        finding = self.findings[0]
        self.assertEqual(finding.rule, "openai-key")
        self.assertGreaterEqual(finding.match_length, len(SECRET))

    def test_masked_excerpt_keeps_only_six_characters_per_side(self):
        excerpt = privacy_scan._mask_excerpt(LINE)
        self.assertIn("***", excerpt)
        self.assertNotIn(SECRET[:8], excerpt)
        self.assertLessEqual(len(excerpt), 160)


class TestDefaultReportDoesNotEchoTheSecret(unittest.TestCase):

    def setUp(self):
        self.findings = privacy_scan.scan_text(LINE, "test", "config.py")
        self.secret_run = re.compile(re.escape(SECRET[:8]))

    def test_text_report_has_location_rule_and_length_only(self):
        output = capture_report(self.findings)
        self.assertIn("config.py:1", output)
        self.assertIn("openai-key", output)
        self.assertIn("命中长度", output)
        self.assertNotIn("API_KEY", output)
        self.assertIsNone(self.secret_run.search(output))

    def test_json_report_omits_excerpt_by_default(self):
        output = capture_report(self.findings, as_json=True)
        self.assertIsNone(self.secret_run.search(output))
        payload = json.loads(output)
        self.assertEqual(len(payload["findings"]), 1)
        self.assertNotIn("excerpt", payload["findings"][0])
        self.assertGreaterEqual(payload["findings"][0]["match_length"], len(SECRET))

    def test_show_excerpt_still_masks_the_middle(self):
        output = capture_report(self.findings, as_json=True, show_excerpt=True)
        payload = json.loads(output)
        excerpt = payload["findings"][0]["excerpt"]
        self.assertIn("***", excerpt)
        self.assertNotIn(SECRET, excerpt)
        self.assertIsNone(self.secret_run.search(excerpt))


class TestCommandLine(unittest.TestCase):

    def test_cli_default_output_is_masked(self):
        directory = tempfile.mkdtemp(prefix="zju-privacy-")
        path = os.path.join(directory, "leak.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(LINE + "\n")
        try:
            result = subprocess.run(
                [sys.executable, os.path.join(ROOT, "tools", "privacy_scan.py"),
                 "--root", directory],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        finally:
            import shutil

            shutil.rmtree(directory, ignore_errors=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn(SECRET, result.stdout)
        self.assertIsNone(re.search(re.escape(SECRET[:8]), result.stdout))
        self.assertIn("openai-key", result.stdout)

    def test_cli_show_excerpt_is_masked(self):
        directory = tempfile.mkdtemp(prefix="zju-privacy-")
        path = os.path.join(directory, "leak.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(LINE + "\n")
        try:
            result = subprocess.run(
                [sys.executable, os.path.join(ROOT, "tools", "privacy_scan.py"),
                 "--root", directory, "--show-excerpt"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        finally:
            import shutil

            shutil.rmtree(directory, ignore_errors=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn(SECRET, result.stdout)
        self.assertIn("***", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
