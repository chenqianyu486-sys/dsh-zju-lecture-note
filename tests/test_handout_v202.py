# -*- coding: utf-8 -*-
"""v2.0.2：讲义 PDF 的格式规范（参考图视觉 + 全标记语义 + 数学环境）。

守四件事：

1. 标题编号由渲染器生成，手写前缀一律剥掉；
2. 底稿标记（直觉/定义/定理/例/证明/练习/边注/强调/…）都落到对应装置；
3. 数学环境（pmatrix / cases / aligned）与多字母标识符不再让 PDF 编译失败；
4. 版心为右侧留白（边注栏），模板自包含、不拉 Typst Universe 包。
"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zju_lecture import handout  # noqa: E402
from zju_lecture.handout import compile_handout, render_handout  # noqa: E402
from zju_lecture.study_notes import find_typst, latex_to_typst  # noqa: E402


NOTE = r"""# 复变函数 第 3 讲：留数定理

## 一、留数的定义

[直觉] 留数就是 Laurent 展开里负一次幂的系数。

在孤立奇点 $z_0$ 附近，任何解析函数都可以展成 Laurent 级数

$$
\sum_{n=-\infty}^{\infty} a_n (z-z_0)^n
$$

[定理] 留数定理 —— $\int_C f(z)\,dz = 2\pi i \sum_k \operatorname{Res}(f, z_k)$ <def:res>

[证明] 把 $C$ 内部挖去以各奇点为中心的小圆，每一项趋于 $2\pi i$ 倍留数。

[例] 单位圆上的 $\int_C \frac{1}{z^2+1}\,dz$

[练习] 求 $f(z) = \frac{e^z}{z(z-1)}$ 的留数。 ____ ____

[边注] 留数与「负一次幂」这说法之间，漏了什么前提？

## 二、留数定理

见定理 @def:res。正文里的挖空：____
"""


class TestHeadingNumbering(unittest.TestCase):
    def test_hand_written_numbers_are_stripped(self):
        rendered = render_handout(
            "# 标题\n\n## 一、留数的定义\n\n正文。\n\n### 2.1 子节\n\n正文。\n\n## 3. 例题\n"
        )
        self.assertIn("= 留数的定义", rendered.typst)
        self.assertIn("== 子节", rendered.typst)
        self.assertIn("= 例题", rendered.typst)
        self.assertNotIn("一、留数", rendered.typst)
        self.assertNotIn("2.1 子节", rendered.typst)
        self.assertNotIn("3. 例题", rendered.typst)

    def test_numbering_is_left_to_typst(self):
        rendered = render_handout("# 标题\n\n## 一节\n\n正文。\n")
        # 模板里统一设置 numbering，正文标题不再自带编号。
        self.assertIn('heading(numbering: "1.1")', rendered.typst)


class TestMarkerDevices(unittest.TestCase):
    def setUp(self):
        self.rendered = render_handout(NOTE)

    def test_intuition_is_a_soft_note_block(self):
        self.assertIn("#note[", self.rendered.typst)

    def test_knots_are_numbered_by_section(self):
        self.assertIn('#theorem("1.1", title: [留数定理])[', self.rendered.typst)
        self.assertIn('#example("1.2")[', self.rendered.typst)

    def test_proof_practice_and_margin_notes(self):
        self.assertIn("#proof[", self.rendered.typst)
        self.assertIn("#yourturn[", self.rendered.typst)
        self.assertIn("#recall[", self.rendered.typst)

    def test_warning_sidenote_uses_round_brackets(self):
        rendered = render_handout("# 标题\n\n## 节\n\n[边注!] 看这里。\n")
        self.assertIn("#sidenote([看这里。], symbol: [!])", rendered.typst)

    def test_practice_block_drops_short_fillins(self):
        fragment = self.rendered.typst.split("#yourturn[", 1)[1].split("]", 1)[0]
        self.assertNotIn("#fillin", fragment)

    def test_body_fillin_and_gap(self):
        rendered = render_handout(
            "# 标题\n\n## 节\n\n正文里留空：____\n\n[证明] 关键一步 [缺口: 小圆上的积分]。\n"
        )
        self.assertIn("#fillin(width: 2.2cm)", rendered.typst)
        self.assertIn("#gap[小圆上的积分]", rendered.typst)

    def test_inline_emphasis_devices(self):
        rendered = render_handout(
            "# 标题\n\n## 节\n\n[强调] 这条要记住。\n\n[易错] 别把边界算进去。\n\n[弱注] 可跳过。\n\n[分隔]\n"
        )
        for device in ("#accent[", "#warn[", "#aside[", "#divider"):
            self.assertIn(device, rendered.typst)


class TestCrossReferences(unittest.TestCase):
    def test_label_and_reference_render_numbers(self):
        rendered = render_handout(NOTE)
        self.assertIn("<def:res>", rendered.typst)
        self.assertIn("#link(<def:res>)[1.1]", rendered.typst)

    def test_dangling_reference_is_reported(self):
        rendered = render_handout("# 标题\n\n## 节\n\n见 @def:missing 的定义。\n")
        self.assertTrue(any("悬空引用" in item for item in rendered.warnings))


class TestBudget(unittest.TestCase):
    def test_too_many_boxes_in_one_section_is_reported(self):
        text = (
            "# 标题\n\n## 一节\n\n正文。\n\n"
            "[定义] a —— b\n\n[定理] c —— d\n\n[例] e —— f\n"
        )
        rendered = render_handout(text)
        self.assertTrue(
            any("视觉预算" in item for item in rendered.warnings), rendered.warnings
        )

    def test_box_ratio_is_reported(self):
        text = (
            "# 标题\n\n## 一节\n\n"
            "[定义] a —— b\n\n[定理] c —— d\n\n[例] e —— f\n\n"
            + "\n\n".join("正文第 %d 段。" % index for index in range(8))
            + "\n"
        )
        rendered = render_handout(text)
        self.assertTrue(
            any("方框:正文" in item for item in rendered.warnings), rendered.warnings
        )


class TestTemplateMatchesReference(unittest.TestCase):
    def setUp(self):
        path = os.path.join(ROOT, "zju_lecture", "handout_prelude.typ")
        with open(path, encoding="utf-8") as handle:
            self.template = handle.read()

    def test_template_is_self_contained(self):
        self.assertNotIn('#import "@preview/', self.template)

    def test_right_side_margin_holds_the_sidenotes(self):
        self.assertIn("right: 3.9cm", self.template)
        self.assertIn("#let sidenote(", self.template)

    def test_reference_palette_and_devices_exist(self):
        for token in ("#33609B", "#20705F", "#8F6218"):
            self.assertIn(token, self.template)
        for device in ("#let note(", "#let theorem(", "#let yourturn(", "#let proof(", "#let toc("):
            self.assertIn(device, self.template)

    def test_body_parameters_match_the_renderer_constants(self):
        # 规范里「leading 0.72em / spacing 0.95em」在模板与 Python 常量里必须同值。
        self.assertIn("leading: " + handout.BODY_LEADING, self.template)
        self.assertIn("spacing: " + handout.BODY_SPACING, self.template)
        self.assertIn(
            "above: " + handout.EQUATION_BLOCK_SPACING, self.template
        )


class TestMathEnvironments(unittest.TestCase):
    def test_pmatrix_becomes_mat(self):
        converted, issues = latex_to_typst(r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}")
        self.assertEqual(converted, "mat(1, 2; 3, 4)")
        self.assertEqual(issues, [])

    def test_bmatrix_keeps_the_bracket(self):
        converted, _ = latex_to_typst(r"\begin{bmatrix} a & b \\ c & d \end{bmatrix}")
        self.assertEqual(converted, 'mat(delim: "[", a, b; c, d)')

    def test_cases_and_aligned(self):
        converted, _ = latex_to_typst(
            r"\begin{cases} x & x > 0 \\ -x & x \le 0 \end{cases}"
        )
        self.assertEqual(converted, "cases(x & x > 0, -x & x ≤ 0)")
        converted, _ = latex_to_typst(r"\begin{aligned} a &= b \\ c &= d \end{aligned}")
        self.assertIn("&=", converted)
        self.assertIn("\\", converted)

    def test_multi_letter_identifiers_do_not_break_typst(self):
        self.assertEqual(latex_to_typst("B^2 - 4AC")[0], "B^2 - 4A C")
        self.assertEqual(latex_to_typst("e^{-st}")[0], "e^(-s t)")
        self.assertEqual(latex_to_typst(r"\operatorname{Res}(f, z_0)")[0], '"Res"(f, z_0)')
        self.assertEqual(latex_to_typst(r"\mathcal{L}\{f(t)\}")[0], "cal(L){f(t)}")

    def test_unknown_environment_is_named(self):
        converted, issues = latex_to_typst(r"\begin{tikz} \draw (0,0); \end{tikz}")
        self.assertTrue(any("tikz" in item for item in issues), issues)
        self.assertIsInstance(converted, str)


class TestRealNotesCompile(unittest.TestCase):
    """两份真实讲义的公式曾让 PDF 直接编译失败，这里守住回归。"""

    def _compile(self, text):
        rendered = render_handout(text)
        with tempfile.TemporaryDirectory() as directory:
            result = compile_handout(
                rendered.typst,
                os.path.join(directory, "out.pdf"),
                workspace_root=directory,
            )
            return rendered, result

    @unittest.skipUnless(find_typst(), "本机没有 Typst，跳过真实编译")
    def test_marker_rich_note_compiles(self):
        rendered, result = self._compile(NOTE)
        self.assertTrue(result.ok, result.errors[:4])
        self.assertGreaterEqual(result.pages, 2)
        self.assertEqual(rendered.warnings, [])

    @unittest.skipUnless(find_typst(), "本机没有 Typst，跳过真实编译")
    def test_math_environments_compile(self):
        text = (
            "# 标题\n\n## 节\n\n"
            r"$$\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}$$"
            "\n\n"
            r"$$\Delta = B^2 - 4AC,\qquad e^{-st}$$"
            "\n"
        )
        _rendered, result = self._compile(text)
        self.assertTrue(result.ok, result.errors[:4])


class TestSpecCoversBothPipelines(unittest.TestCase):
    def test_spec_is_shared_by_handout_and_study_notes(self):
        path = os.path.join(ROOT, "skills", "scholia-notes", "references", "format-spec.md")
        with open(path, encoding="utf-8") as handle:
            spec = handle.read()
        self.assertIn("阅读版讲义", spec)
        self.assertIn("zju_write_note", spec)
        self.assertIn("pmatrix", spec)
        self.assertIn("cases", spec)
        self.assertIn("3 行书写横线", spec)
        self.assertNotIn("走的是另一套直排模板", spec)

    def test_summarizer_skill_mentions_the_markers(self):
        path = os.path.join(ROOT, "skills", "zju-lecture-summarizer", "SKILL.md")
        with open(path, encoding="utf-8") as handle:
            skill = handle.read()
        self.assertIn("阅读版 PDF 的排版标记", skill)
        self.assertIn("[直觉]", skill)
        self.assertIn("format-spec.md", skill)


if __name__ == "__main__":
    unittest.main()
