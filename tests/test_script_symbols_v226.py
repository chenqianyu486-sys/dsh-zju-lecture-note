# -*- coding: utf-8 -*-
"""v2.2.6：上下标里的符号名被逐字母拆开的回归（session-42baa52c）。

守五件事：

1. **``29^{\\circ}`` 排成 ``29^(degree)``**：旧实现把 ``\\circ`` 先转成 Typst 的
   ``compose``，再被``逐字母拆词``规则拆成 ``(c o m p o s e)`` —— PDF 右上角
   直接印出单词 ``compose``（用户截图里的 ``sin 29^{compose}``）。
   同一类错误波及**所有**多字母符号名：``x^{\\alpha}`` → ``(a l p h a)``、
   ``x_{\\theta}`` → ``(t h e t a)``。
2. **裸字母串仍然要拆**：``a_{ij}`` → ``a_(i j)``、``u_{tt}`` → ``(t t)``，
   这是拆词规则本来的用途，不能一起废掉。
3. **不带花括号的命令也要进括号**：``29^\\circ``、``\\sum_{n=1}^\\infty``。
   只处理反斜杠命令；``x_1``、``a_n`` 保持原样（typst 本来就认）。
4. **``\\left`` / ``\\right`` 的分隔符不能丢**：``\\left\\lvert … \\right\\rvert``、
   ``\\left\\| … \\right\\|``、``\\lVert … \\rVert`` 曾经整段被吞（绝对值与
   范数竖线消失），``\\left.`` 还把那个点印进正文。
5. **幂等**：``latex_to_typst`` 跑两遍必须完全相同 —— 这是本项目的铁律。
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zju_lecture.handout import render_handout  # noqa: E402
from zju_lecture.study_notes import (  # noqa: E402
    _LATEX_SYMBOLS,
    _TYPST_BARE_NAMES,
    latex_to_typst,
)


class TestScriptSymbols(unittest.TestCase):
    """上下标内容里的 Typst 符号名必须原样保留。"""

    def test_circ_becomes_degree(self):
        self.assertEqual(latex_to_typst(r"x^{\circ}")[0], "x^(degree)")
        self.assertEqual(latex_to_typst(r"29^{\circ}")[0], "29^(degree)")
        # 不带花括号的写法同样是角度。
        self.assertEqual(latex_to_typst(r"29^\circ")[0], "29^(degree)")

    def test_the_reported_formula(self):
        """用户截图里的那条公式：``sin 29^{compose}`` 不能再出现。"""
        converted, warnings = latex_to_typst(r"\sin 29^{\circ}")
        self.assertEqual(converted, "sin 29^(degree)")
        self.assertEqual(warnings, [])
        self.assertNotIn("compose", converted)

    def test_greek_letters_in_scripts(self):
        for command, letter in (
            ("alpha", "alpha"),
            ("theta", "theta"),
            ("pi", "pi"),
            ("Omega", "Omega"),
            ("varepsilon", "epsilon"),
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    latex_to_typst("x^{\\" + command + "}")[0], "x^(" + letter + ")"
                )
                self.assertEqual(
                    latex_to_typst("x_{\\" + command + "}")[0], "x_(" + letter + ")"
                )

    def test_every_word_symbol_survives_a_script(self):
        """符号表里所有「多字母 ASCII」值，放进上下标都不能被拆开。

        这是这个 bug 的**一般形式**：只要有人往 ``_LATEX_SYMBOLS`` 里加一个
        ``foo: "bar"``，``x^{\\foo}`` 就必须得到 ``x^(bar)``，而不是
        ``x^(b a r)``。
        """
        for command, value in _LATEX_SYMBOLS.items():
            if not re.fullmatch(r"[A-Za-z]{2,}", value):
                continue
            expected = "degree" if command == "circ" else value
            with self.subTest(command=command, value=value):
                converted, _warnings = latex_to_typst("x_{\\" + command + "}")
                self.assertEqual(converted, "x_(" + expected + ")")

    def test_bare_names_cover_every_word_symbol(self):
        """``_TYPST_BARE_NAMES`` 必须收得住符号表产出的每一个名字。

        少了就会在**第二次**转换时被拆散（``(degree)`` → ``(d e g r e e)``），
        幂等会静默失效。
        """
        produced = {
            "degree",
            "compose",
            "thin",
            "med",
            "wide",
            "quad",
        } | {w for w in _LATEX_SYMBOLS.values() if re.fullmatch(r"[A-Za-z]+", w)}
        missing = sorted(produced - _TYPST_BARE_NAMES)
        self.assertEqual(missing, [])


class TestPlainLetterRuns(unittest.TestCase):
    """拆词规则只针对**没转换过**的裸字母串。"""

    def test_two_letter_subscript_still_splits(self):
        self.assertEqual(latex_to_typst("a_{ij}")[0], "a_(i j)")
        self.assertEqual(latex_to_typst("u_{tt}")[0], "u_(t t)")

    def test_three_letter_subscript_still_splits(self):
        self.assertEqual(latex_to_typst("a_{xyz}")[0], "a_(x y z)")

    def test_math_operator_names_are_not_split(self):
        self.assertEqual(latex_to_typst(r"x^{\sin y}")[0], "x^(sin y)")
        self.assertEqual(latex_to_typst(r"A^{\mathrm{T}}")[0], 'A^("T")')


class TestUnbracedScripts(unittest.TestCase):
    """不带花括号的脚本命令补一层括号，裸字母/数字保持原样。"""

    def test_unbraced_command_gets_parentheses(self):
        self.assertEqual(latex_to_typst(r"x^\alpha")[0], "x^(alpha)")
        self.assertEqual(latex_to_typst(r"x^\prime")[0], "x^(′)")

    def test_sum_with_unbraced_index(self):
        self.assertEqual(
            latex_to_typst(r"\sum_{n=1}^\infty")[0], "sum_(n = 1)^(∞)"
        )

    def test_plain_letter_and_digit_unchanged(self):
        # 既有输出不能因为这次修复而变化。
        self.assertEqual(latex_to_typst("x_1")[0], "x_1")
        self.assertEqual(latex_to_typst("a_n")[0], "a_n")
        self.assertEqual(latex_to_typst("x^2")[0], "x^2")


class TestLeftRightDelimiters(unittest.TestCase):
    r"""``\left`` / ``\right`` 后面跟的分隔符必须留下。"""

    def test_absolute_value_bars(self):
        self.assertEqual(
            latex_to_typst(r"\left\lvert \Delta x/x_0\right\rvert")[0],
            "| Delta x/x_0 |",
        )
        self.assertEqual(latex_to_typst(r"\left| x \right|")[0], "| x |")

    def test_norm_bars(self):
        self.assertEqual(latex_to_typst(r"\lVert x \rVert")[0], "‖ x ‖")
        self.assertEqual(
            latex_to_typst(r"\left\lVert x \right\rVert")[0], "‖ x ‖"
        )
        self.assertEqual(latex_to_typst(r"\left\| x \right\|")[0], "‖ x ‖")

    def test_invisible_delimiter_leaves_no_dot(self):
        converted, _warnings = latex_to_typst(r"\left. \frac{df}{dx} \right|_0")
        self.assertNotIn(".", converted.replace("frac", ""))
        self.assertIn("|", converted)

    def test_braces_keep_escapes(self):
        self.assertEqual(latex_to_typst(r"\left\{ x \right\}")[0], "\\{ x \\}")

    def test_sizing_commands_are_dropped(self):
        for command in ("big", "Big", "bigl", "Bigr", "bigg"):
            with self.subTest(command=command):
                converted, warnings = latex_to_typst("\\" + command + "( x )")
                self.assertEqual(converted, "( x )")
                self.assertEqual(warnings, [])

    def test_percent_is_not_reported_as_unmapped(self):
        converted, warnings = latex_to_typst(r"90\%")
        self.assertEqual(converted, "90 %")
        self.assertEqual(warnings, [])


class TestIdempotency(unittest.TestCase):
    """转换两次 == 转换一次。"""

    CORPUS = [
        r"\sin 29^{\circ}",
        r"29^\circ",
        r"x^{\alpha}",
        r"x_{\theta}",
        r"\left\lvert \Delta x/x_0\right\rvert",
        r"\lVert x \rVert",
        r"\left. \frac{df}{dx} \right|_{x=0}",
        r"\sum_{n=1}^{\infty} \frac{a_n}{s^n}",
        r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}",
        r"e^{-st}",
        r"B^2 - 4AC",
        r"\big( \frac{a}{b} \big)",
        r"90\%",
    ]

    def test_round_trip(self):
        for latex in self.CORPUS:
            with self.subTest(latex=latex):
                once, _ = latex_to_typst(latex)
                twice, _ = latex_to_typst(once)
                self.assertEqual(once, twice)


class TestEndToEnd(unittest.TestCase):
    """走一遍讲义的渲染路径，确认坏词没有落进 ``main.typ``。"""

    NOTE = """# 微分

## 线性近似

[例] 例 1：用微分求 $\\sin 29^{\\circ}$ 的近似值 —— **题目** 已知
$\\sin 30^{\\circ}$ 与 $\\cos 30^{\\circ}$ 都容易算。**切入点** 取
$f(x)=\\sin x$，$x_0=30^{\\circ}$。**关键步骤** 故

$$
\\sin 29^{\\circ}\\approx \\sin 30^{\\circ}+\\cos 30^{\\circ}\\cdot\\left(-\\frac{\\pi}{180}\\right)
$$
"""

    def test_handout_contains_degree_not_compose(self):
        result = render_handout(self.NOTE, title="微分")
        self.assertIn("29^(degree)", result.typst)
        self.assertNotIn("compose", result.typst)
        self.assertNotIn("a l p h a", result.typst)
        # 绝对值 / 范数那类空转不能把括号吞掉（这里是 `\left(` / `\right)`）。
        self.assertIn("frac(pi, 180)", result.typst)


if __name__ == "__main__":
    unittest.main()
