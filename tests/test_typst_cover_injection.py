#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Typst 封面注入（安全审查 P0-4 / 7.8）。

``_render_cover`` 以前把封面字段直接拼进 ``"…"``，而正文转义不处理双引号：
一个 ``x" + #read("/etc/passwd") + "`` 就能闭合字符串并执行任意 Typst 代码。

现在拆成两个函数：
* ``escape_typst_text`` —— 正文 markup，行为不变；
* ``escape_typst_string`` —— 字符串字面量，转义 ``\\`` / ``"`` / 换行 / 制表，
  并剥掉裸 ``\\r``。
封面改用 prelude 里的 ``#scholia-cover(title: "…", …)``，只传命名参数。
"""

import os
import shutil
import tempfile
import unittest

from zju_lecture.study_notes import (
    compile_project,
    escape_typst_string,
    escape_typst_text,
    find_typst,
    render_typst,
)

FIELDS = ("title", "subtitle", "author", "date", "kicker")

PAYLOADS = (
    'x" + str(1+1) + "',
    "\\",
    "#",
    "$",
    '\n#read("/etc/passwd")',
)


def make_draft(**overrides):
    values = {
        "title": "复变函数",
        "subtitle": "留数定理",
        "author": "作者",
        "date": "2026-11-07",
        "kicker": "MATH",
    }
    values.update(overrides)
    lines = ["# 封面", ""]
    lines.extend(f"- {key}: {value}" for key, value in values.items())
    lines.extend(["", "# 第一节", "", "正文内容。", ""])
    return "\n".join(lines)


def cover_line(typst_source):
    for line in typst_source.splitlines():
        if line.startswith("#scholia-cover("):
            return line
    return ""


def count_unescaped_quotes(text):
    count = 0
    escaped = False
    for char in text:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"':
            count += 1
    return count


class TestEscapeTypstString(unittest.TestCase):

    def test_escapes_quotes_backslashes_and_control_characters(self):
        self.assertEqual(escape_typst_string('a"b'), 'a\\"b')
        self.assertEqual(escape_typst_string("a\\b"), "a\\\\b")
        self.assertEqual(escape_typst_string("a\nb"), "a\\nb")
        self.assertEqual(escape_typst_string("a\tb"), "a\\tb")

    def test_strips_bare_carriage_returns(self):
        self.assertEqual(escape_typst_string("a\r\nb"), "a\\nb")
        self.assertEqual(escape_typst_string("a\rb"), "ab")

    def test_text_escape_is_unchanged_for_prose(self):
        # 正文转义只处理 markup 敏感字符，不转义双引号（引号在 markup 里无害）。
        self.assertEqual(escape_typst_text('他说"你好"'), '他说"你好"')
        self.assertIn("\\_", escape_typst_text("a_1"))


class TestCoverUsesStringLiterals(unittest.TestCase):

    def test_every_field_is_escaped_on_one_line(self):
        for field in FIELDS:
            for payload in PAYLOADS:
                with self.subTest(field=field, payload=payload):
                    line = cover_line(render_typst(make_draft(**{field: payload})).typst)
                    self.assertTrue(line.startswith("#scholia-cover("), line)
                    self.assertNotIn("\n", line)
                    # 每个字段的值都必须是完整的字符串字面量：未转义引号成对。
                    self.assertEqual(count_unescaped_quotes(line) % 2, 0, line)

    def test_quote_payload_is_escaped_and_stays_inside_the_literal(self):
        source = render_typst(
            make_draft(title='x" + str(1+1) + "')
        ).typst
        line = cover_line(source)
        self.assertIn('title: "x\\" + str(1+1) + \\""', line)
        self.assertNotIn('title: "x"', line)

    def test_newline_payload_cannot_break_out_of_the_cover(self):
        # 草稿按行解析，字段值里的裸换行只能结束该字段；剩下的 `#read(...)`
        # 落到正文，并被正文转义成不可执行的 `\#read(...)`。
        source = render_typst(make_draft(title='\n#read("/etc/passwd")')).typst
        line = cover_line(source)
        self.assertNotIn("#read", line)
        self.assertIn("\\#read(\"/etc/passwd\")", source)
        self.assertNotIn("\n#read(", source)

    def test_backslash_payload_is_doubled(self):
        line = cover_line(render_typst(make_draft(author="\\")).typst)
        self.assertIn('author: "\\\\"', line)


@unittest.skipUnless(find_typst(), "本机没有 Typst，跳过真实编译")
class TestCompileDoesNotExecuteInjection(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="zju-cover-")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_injected_fields_compile_without_executing(self):
        # `/nonexistent-zju-sentinel` 只可能由注入的 #read 打开；转义正确时
        # 它只是封面上的字面文字，编译必须成功。
        payload = 'a" + #read("/nonexistent-zju-sentinel") + "'
        for index, field in enumerate(FIELDS):
            with self.subTest(field=field):
                rendered = render_typst(make_draft(**{field: payload}))
                project = os.path.join(self.directory, f"case-{index}")
                result = compile_project(project, rendered.typst, make_png=False)
                self.assertTrue(result.ok, result.errors or result.output)
                with open(os.path.join(project, "out.pdf"), "rb") as handle:
                    self.assertGreater(len(handle.read()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
