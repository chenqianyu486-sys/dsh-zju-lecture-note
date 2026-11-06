#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI ``cookie --reveal`` 的二次确认（安全审查 P2-3）。

``--reveal`` 会把一个仍然有效的会话 Cookie 打进终端与 shell 历史。
现在非交互式终端直接拒绝，交互式终端必须输入 ``yes``；确认发生在读取
Edge 之前，所以拒绝时连 Cookie 都不会被读取。
"""

import io
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zju_lecture import cli  # noqa: E402


class _TtyStdin(io.StringIO):
    def isatty(self):
        return True


class TestCookieRevealConfirmation(unittest.TestCase):

    def _run(self, stdin, reader, answer=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        patches = [
            mock.patch.object(sys, "argv", ["zju-lecture", "cookie", "--reveal"]),
            mock.patch.object(sys, "stdin", stdin),
            mock.patch.object(sys, "stdout", stdout),
            mock.patch.object(sys, "stderr", stderr),
            mock.patch.object(cli, "get_edge_cookie", reader),
        ]
        if answer is not None:
            patches.append(mock.patch("builtins.input", return_value=answer))
        for patcher in patches:
            patcher.start()
        try:
            cli.main()
        finally:
            for patcher in reversed(patches):
                patcher.stop()
        return stdout.getvalue(), stderr.getvalue()

    def test_non_tty_is_refused_before_reading_the_cookie(self):
        reader = mock.Mock(return_value="sid=test")
        stdout, stderr = self._run(io.StringIO(), reader)
        self.assertEqual(stdout, "")
        self.assertIn("--reveal", stderr)
        reader.assert_not_called()

    def test_interactive_no_is_cancelled(self):
        reader = mock.Mock(return_value="sid=test")
        stdout, _stderr = self._run(_TtyStdin(), reader, answer="no")
        self.assertIn("已取消", stdout)
        reader.assert_not_called()

    def test_interactive_yes_prints_the_cookie(self):
        reader = mock.Mock(return_value="sid=test")
        stdout, _stderr = self._run(_TtyStdin(), reader, answer="yes")
        reader.assert_called_once()
        self.assertIn("sid=test", stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
