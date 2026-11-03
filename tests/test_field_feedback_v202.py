#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the PR #2 review follow-up (on top of v2.0.2).

Two findings from running the plugin against a real 22k-character lecture note:

* the autofix rewrote formulas **inside backtick code spans**. A note that
  shows ``\\frac12`` in a code span is documenting the unfinished form on
  purpose; rewriting it turns the example into the finished one and the lint
  report then says "通过", so nobody notices. Single-backtick spans were
  already protected in 1.5.1; a span delimited by two or more backticks was
  not, because ``_apply_outside_code`` used to toggle on every single
  backtick. It now pairs *runs* of backticks, the way Markdown reads them.
* the connection-refused diagnosis said ``代理很可能没启动（(未设置)）``. Without
  naming ``HTTPS_PROXY`` / ``HTTP_PROXY`` the hint does not tell the user which
  variable to look at — and the existing assertion in ``test_plugin.py`` only
  passed because the machine happened to export a proxy variable.
"""

import contextlib
import os
import sys
import unittest
import urllib.error
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from zju_lecture import client as client_module
from zju_lecture.note_lint import fix_markdown

_PROXY_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


@contextlib.contextmanager
def _clean_proxy_env(**overrides):
    """Run with no proxy variable in the environment, then apply *overrides*.

    ``os.environ`` is case-insensitive on Windows, so ``mock.patch.dict`` with a
    dict holding both cases would let the empty lowercase entry overwrite the
    uppercase one. Set and restore the keys by hand instead.
    """
    saved = {key: os.environ.get(key) for key in _PROXY_KEYS}
    try:
        for key in _PROXY_KEYS:
            os.environ.pop(key, None)
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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

    def test_normalize_math_is_code_aware_on_its_own(self):
        """The skip must live in ``_normalize_math``, not only at a call site."""
        from zju_lecture.note_lint import _normalize_math

        fixed, count = _normalize_math("`\\frac12`")
        self.assertEqual(fixed, "`\\frac12`")
        self.assertEqual(count, 0)

    def test_double_backtick_span_is_untouched(self):
        text = "示例：``\\frac12`` 是错的\\n"
        fixed, applied = fix_markdown(text)
        self.assertEqual(fixed, text)
        self.assertEqual(applied, [])

    def test_triple_backtick_span_is_untouched(self):
        text = "示例：```\\dfrac{a}{b}``` 是错的\\n"
        fixed, applied = fix_markdown(text)
        self.assertEqual(fixed, text)
        self.assertEqual(applied, [])

    def test_backtick_inside_double_span_is_content(self):
        text = "示例：``a ` b \\frac12`` 是错的\\n"
        fixed, applied = fix_markdown(text)
        self.assertEqual(fixed, text)
        self.assertEqual(applied, [])

    def test_math_next_to_a_code_span_is_still_fixed(self):
        text = "公式 $\\frac12$ 与 `\\frac12`\\n"
        fixed, applied = fix_markdown(text)
        self.assertIn("$\\frac{1}{2}$", fixed)
        self.assertIn("`\\frac12`", fixed)
        self.assertTrue(applied)


class ProxyHintNamesTheVariable(unittest.TestCase):
    """A refused connection must point at the variable to inspect."""

    def _describe(self):
        return client_module.describe_network_error(
            urllib.error.URLError(ConnectionRefusedError(10061, "由于目标计算机积极拒绝。"))
        )

    def test_connection_refused_names_proxy_variables(self):
        with _clean_proxy_env():
            message = self._describe()
        self.assertIn("代理", message)
        self.assertIn("HTTPS_PROXY", message)
        self.assertIn("HTTP_PROXY", message)
        self.assertNotIn("((", message)

    def test_connection_refused_shows_the_configured_proxy(self):
        with _clean_proxy_env(HTTPS_PROXY="http://127.0.0.1:7897"):
            message = self._describe()
        self.assertIn("HTTPS_PROXY=http://127.0.0.1:7897", message)


if __name__ == "__main__":
    unittest.main()
