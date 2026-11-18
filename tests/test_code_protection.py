"""#16 回归：代码示例（围栏 / 行内）在两条 PDF 链路与机械修复里逐字节保留。

代码里的 ``# 注释`` 不是标题、``$\\frac12$`` 不是待转换公式、``<!-- … -->`` 不是
待清理注释；嵌套围栏（````markdown 里嵌 ```latex）与 ~~~ 围栏也不能被提前闭合。
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zju_lecture import handout, note_lint, study_notes  # noqa: E402


class TestStudyCodeProtection(unittest.TestCase):
    def test_fenced_code_keeps_math_comments_and_headings(self):
        code = '# Cover\n<!-- example -->\nif True:\n    print("$\\frac12$")'
        result = study_notes.render_typst("## Example\n\n```python\n" + code + "\n```")
        self.assertIn("#raw(" + json.dumps(code, ensure_ascii=False), result.typst)
        self.assertEqual(result.warnings, [])

    def test_inline_code_is_not_math_or_comment(self):
        code = r"$\frac{1}{2}$ <!-- example -->"
        result = study_notes.render_typst("Use `" + code + "` literally.")
        self.assertIn(code, result.typst)
        self.assertEqual(result.warnings, [])

    def test_multibacktick_inline_code_preserved(self):
        result = study_notes.render_typst("Use ``a ` $\\frac12$`` literally.")
        self.assertIn("a ` $\\frac12$", result.typst)

    def test_code_heading_is_not_document_structure(self):
        result = study_notes.render_typst("```python\n# important comment\nprint(1)\n```")
        self.assertIn('#raw("# important comment\\nprint(1)"', result.typst)
        self.assertNotIn("\n= important comment", result.typst)

    def test_nested_fences_keep_inner_example(self):
        code = "```html\n<!-- example -->\n<p>x</p>\n```"
        result = study_notes.render_typst("# Test\n\n````markdown\n" + code + "\n````")
        self.assertIn("#raw(" + json.dumps(code, ensure_ascii=False), result.typst)


class TestHandoutCodeProtection(unittest.TestCase):
    def test_nested_fences_and_comments_literal(self):
        code = "# Cover\n```html\n<!-- example -->\n<p>x</p>\n```"
        result = handout.render_handout("# Test\n\n````markdown\n" + code + "\n````")
        self.assertIn("#raw(" + json.dumps(code, ensure_ascii=False), result.typst)
        self.assertEqual(result.title, "Test")
        self.assertEqual(result.warnings, [])

    def test_inline_comment_example_not_removed(self):
        result = handout.render_handout("# Test\n\nUse `<!-- example -->` literally.")
        self.assertIn('#raw("<!-- example -->")', result.typst)

    def test_code_heading_not_fallback_cover(self):
        result = handout.render_handout("```python\n# important comment\nprint(1)\n```")
        self.assertEqual(result.title, "")
        self.assertIn('#raw("# important comment\\nprint(1)"', result.typst)


class TestStructuralLabelValidation(unittest.TestCase):
    def test_plain_paragraph_label_is_actionable_warning(self):
        issues = note_lint.check_markdown("# 标题\n\n普通段落末尾 <def:x>。")
        finding = next(
            (item for item in issues if item.code == "label_not_structural"),
            None,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.level, "warn")
        self.assertIn("普通段落末尾不会被编号", finding.hint)

    def test_marker_and_heading_labels_are_structural(self):
        for markdown in (
            "# 标题\n\n[定义] 定义正文 <def:x>",
            "## 定义标题 <def:x>\n\n正文",
        ):
            with self.subTest(markdown=markdown):
                issues = note_lint.check_markdown(markdown)
                self.assertFalse(
                    [item for item in issues if item.code == "label_not_structural"]
                )

    def test_unregistered_reference_is_literal_not_typst_ref(self):
        rendered = study_notes.render_typst(
            "见 @def:x 的定义。\n\n普通段落末尾 <def:x>。"
        )
        self.assertIn(r"\@def:x", rendered.typst)
        self.assertNotIn("@def:x", rendered.typst.replace(r"\@def:x", ""))
        self.assertTrue(any("已按字面量保留" in item for item in rendered.warnings))

    def test_heading_label_stays_a_typst_ref(self):
        rendered = study_notes.render_typst(
            "见 @def:x 的定义。\n\n## 定义标题 <def:x>\n\n正文"
        )
        self.assertRegex(rendered.typst, r"(?<!\\)@def:x")
        self.assertIn("= 定义标题 <def:x>", rendered.typst)
        self.assertFalse(any("未登记为结构标签" in item for item in rendered.warnings))

    def test_registered_reference_stays_a_typst_ref(self):
        rendered = study_notes.render_typst(
            "见 @def:x 的定义。\n\n[定义] 定义正文 <def:x>"
        )
        self.assertRegex(rendered.typst, r"(?<!\\)@def:x")
        self.assertIn("<def:x>", rendered.typst)
        self.assertFalse(any("未登记为结构标签" in item for item in rendered.warnings))


class TestLintCodeProtection(unittest.TestCase):
    def test_fixer_and_linter_respect_fence_length_and_char(self):
        for opening, inner, closing in (
            ("````markdown", "```latex", "````"),
            ("~~~markdown", "```latex", "~~~"),
        ):
            with self.subTest(opening=opening):
                code = opening + "\n" + inner + "\n$$\\frac12$$\n```\n" + closing + "\n"
                self.assertEqual(note_lint.fix_markdown(code), (code, []))
                self.assertEqual(note_lint.check_markdown(code), [])

    def test_fixing_resumes_after_actual_closing_fence(self):
        code = "````markdown\n```latex\n\\frac12\n```\n````\n"
        result, applied = note_lint.fix_markdown(code + "\n$\\frac12$\n")
        self.assertEqual(result, code + "\n$\\frac{1}{2}$\n")
        self.assertTrue(applied)

    def test_multibacktick_inline_not_linted(self):
        self.assertEqual(note_lint.check_markdown("Use ``a ` $\\frac12$`` literally."), [])


@unittest.skipUnless(study_notes.find_typst(), "本机没有 typst，跳过编译测试")
class TestCodeCompiles(unittest.TestCase):
    def test_unregistered_reference_compiles_as_literal(self):
        rendered = study_notes.render_typst(
            "见 @def:x 的定义。\n\n普通段落末尾 <def:x>。"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = study_notes.compile_project(
                directory, rendered.typst, make_png=False
            )
            self.assertTrue(result.ok, result.errors)

    def test_code_samples_compile_in_both_renderers(self):
        markdown = "# Code\n\n```python\n# comment\nprint('$\\frac12$')\n```\n\n正文 $x^2$。"
        with tempfile.TemporaryDirectory() as directory:
            for render in (study_notes.render_typst, handout.render_handout):
                with self.subTest(renderer=render.__name__):
                    rendered = render(markdown)
                    project = os.path.join(directory, render.__name__)
                    result = study_notes.compile_project(project, rendered.typst, make_png=False)
                    self.assertTrue(result.ok, result.errors)


if __name__ == "__main__":
    unittest.main()