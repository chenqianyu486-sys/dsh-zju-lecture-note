#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""镜像 URL 脱敏（安全审查 P1-1 / 7.4）。

``ZJU_TYPST_MIRROR`` 可以是 ``https://user:pass@mirror/base?token=…``。
以前它会原样进入 ``zju_doctor`` 的 mirror 字段、下载进度 stderr 与异常消息，
宿主的日志/会话记录因此替用户保存了一份凭据。

现在：deps 的展示/诊断只保留 ``scheme://host[:port]/path``，并通过
``SecretRedactor``；bridge.js 在转发 stderr 前再做一层 JS 脱敏。
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zju_lecture import deps  # noqa: E402

MIRROR = "https://mirror-user:mirror-pass@mirror.example.com/typst?token=SECRET#frag"
SECRETS = ("mirror-user", "mirror-pass", "SECRET")


class TestRedactUrl(unittest.TestCase):

    def test_keeps_only_scheme_host_port_and_path(self):
        self.assertEqual(
            deps._redact_url(MIRROR),
            "https://mirror.example.com/typst",
        )
        self.assertEqual(
            deps._redact_url("https://mirror.example.com:8443/base/"),
            "https://mirror.example.com:8443/base/",
        )

    def test_non_url_text_is_passed_through_the_redactor(self):
        self.assertEqual(deps._redact_url(""), "")
        self.assertEqual(deps._redact_url("not a url"), "not a url")


class TestDescribeAndProgress(unittest.TestCase):

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"ZJU_TYPST_MIRROR": MIRROR})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_describe_does_not_expose_mirror_credentials(self):
        report = deps.describe("")
        mirror = report["mirror"]
        self.assertEqual(mirror, "https://mirror.example.com/typst")
        for secret in SECRETS:
            self.assertNotIn(secret, mirror)

    def test_progress_scrubs_urls(self):
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            deps._progress(f"首次排版需要 Typst：{MIRROR}")
        output = stream.getvalue()
        self.assertIn("https://mirror.example.com/typst", output)
        for secret in SECRETS:
            self.assertNotIn(secret, output)

    def test_download_failure_message_is_scrubbed(self):
        directory = tempfile.mkdtemp(prefix="zju-deps-")
        target = os.path.join(directory, "typst.zip")

        def fail(*_args, **_kwargs):
            raise RuntimeError(f"connection failed for {MIRROR}")

        stream = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=fail), \
                contextlib.redirect_stderr(stream):
            with self.assertRaises(RuntimeError) as caught:
                deps._download(MIRROR, target, retries=1)
        self.assertIn("https://mirror.example.com/typst", str(caught.exception))
        combined = str(caught.exception) + stream.getvalue()
        for secret in SECRETS:
            self.assertNotIn(secret, combined)


class TestBridgeStderrRedaction(unittest.TestCase):

    def test_redact_stderr_masks_headers_userinfo_and_query_tokens(self):
        script = (
            "import('./lib/bridge.js').then(m => console.log(m.redactStderr("
            "process.argv[1] + '\\n' + process.argv[2] + '\\n' + process.argv[3]"
            ")))"
        )
        payloads = (
            "Cookie: SESSDATA=abc123; _token=def456",
            "https://user:pass@mirror.example.com/base",
            "https://mirror.example.com/x?token=SECRET&key=K",
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script, *payloads],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout
        for secret in ("abc123", "def456", "user:pass", "SECRET", "key=K"):
            self.assertNotIn(secret, output)
        self.assertIn("[REDACTED]", output)
        self.assertIn("https://mirror.example.com/base", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
