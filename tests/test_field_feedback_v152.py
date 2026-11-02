#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the 1.5.1 review follow-up (v1.5.2).

Two findings, both from running 1.5.1 against a real 22k-character lecture note:

* the autofix rewrote formulas **inside backtick code spans**. A note that
  shows ``\\frac12`` in a code span is documenting the unfinished form on
  purpose; rewriting it turns the example into the finished one and the lint
  report then says "通过", so nobody notices.
* the connection-refused diagnosis said ``代理很可能没启动（(未设置)）``. Without
  naming ``HTTPS_PROXY`` / ``HTTP_PROXY`` the hint does not tell the user which
  variable to look at.
"""

import os
import sys
import unittest
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from zju_lecture import client as client_module
from zju_lecture.note_lint import fix_markdown


class InlineCodeSurvivesAutofix(unittest.TestCase):
    """The fixer must not rewrite documentation."""

    def test_backtick_example_keeps_the_wrong_form(self):
        note = (
            "示例：`\\frac12` 与 `\\dfrac{a}{b}` 是错误写法\n"
            "\n"
            "真正要修的：$\\frac12$\n"
        )
        fixed, applied = fix_markdown(note)
        self.assertIn("`\\frac12`", fixed, "反引号里的 \\frac12 被改写了")
        self.assertIn("`\\dfrac{a}{b}`", fixed, "反引号里的 \\dfrac 被改写了")
        self.assertIn("$\\frac{1}{2}$", fixed, "真正的公式没有被修")
        self.assertTrue(applied)

    def test_inline_code_only_line_is_untouched(self):
        text = "说明：`\\dfrac{1}{2}` 这么写\n"
        fixed, applied = fix_markdown(text)
        self.assertEqual(fixed, text)
        self.assertEqual(applied, [])

    def test_fenced_block_still_untouched(self):
        text = "```\n$$z=\\frac12$$\n```\n"
        fixed, applied = fix_markdown(text)
        self.assertEqual(fixed, text)
        self.assertEqual(applied, [])


class ProxyHintNamesTheVariable(unittest.TestCase):
    """A refused connection must point at the variable to inspect."""

    def test_connection_refused_names_proxy_variables(self):
        message = client_module.describe_network_error(
            urllib.error.URLError(ConnectionRefusedError(10061, "由于目标计算机积极拒绝。"))
        )
        self.assertIn("代理", message)
        self.assertIn("HTTPS_PROXY", message)


if __name__ == "__main__":
    unittest.main()
