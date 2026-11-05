# -*- coding: utf-8 -*-
"""v2.2.4：自测题「题干琥珀框 + 框外答案」的回归。

守四件事：

1. `**1.** 题干` + `<details><summary>答案</summary>…</details>` 排成
   `#selftest(1)[题干]`（与「例」同款的琥珀框）与 `#answer("答案")[…]`（框外、淡灰左线）；
2. 答案不再和题目连成一篇，`<details>` / `<summary>` 不会印成字面量；
3. 没有手写编号的题干用计数器兜底；`<summary>` 的文字当答案标签；
4. 两条链路（阅读版 `handout.py` / 填空笔记 `study_notes.py`）行为一致。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zju_lecture.handout import render_handout  # noqa: E402
from zju_lecture.study_notes import latex_to_typst, render_typst  # noqa: E402

NOTE = """## 六、自测题

**1.** 求 $L^{-1}\\left[\\frac{e^{-2s}}{s+3}\\right]$，并指出 $t$ 的范围。

<details>
<summary>答案</summary>

先算 $L^{-1}\\left[\\frac{1}{s+3}\\right]=e^{-3t}$，再延时：

$$
f(t)=e^{-3(t-2)}u(t-2)
$$

易错：指数里是 $-3(t-2)$。

</details>

**2.** 求 $L\\left[t^{2}e^{-t}\\right]$。

<details>
<summary>答案</summary>

$\\frac{2}{(s+1)^{3}}$。

</details>
"""


class TestReadingHandoutSelfTest(unittest.TestCase):
    def setUp(self):
        self.rendered = render_handout(NOTE)
        self.typst = self.rendered.typst

    def test_question_stem_is_an_amber_box(self):
        self.assertIn("#selftest(1)[求 ", self.typst)
        self.assertIn("#selftest(2)[求 ", self.typst)
        # 手写的 `**1.**` 编号交给标签，不再留在题干里
        self.assertNotIn("**1.**", self.typst)
        self.assertEqual(self.rendered.blocks.get("selftest"), 2)

    def test_answer_sits_outside_the_question_box(self):
        first = self.typst.index("#selftest(1)")
        answer = self.typst.index('#answer("答案")')
        self.assertGreater(answer, first)
        # 题干块在答案前就闭合了：答案不在 `#selftest[…]` 里
        stem_end = self.typst.index("]", first)
        self.assertLess(stem_end, answer)
        self.assertIn("先算", self.typst[answer:])

    def test_answer_keeps_display_math_and_paragraphs(self):
        start = self.typst.index('#answer("答案")')
        end = self.typst.index("#selftest(2)")
        answer = self.typst[start:end]
        self.assertIn("$ f(t)=e^(-3(t-2))u(t-2) $", answer)
        self.assertIn("易错", answer)

    def test_details_tags_are_not_printed(self):
        # 模板注释里提到 `<details>` 是正常的；正文里不能出现转义后的标签。
        self.assertNotIn("\\<details\\>", self.typst)
        self.assertNotIn("<summary>", self.typst)

    def test_summary_text_is_the_answer_label(self):
        rendered = render_handout(
            "## 一节\n\n**1.** 题干。\n\n"
            "<details>\n<summary>解析</summary>\n\n正文。\n</details>\n"
        )
        self.assertIn('#answer("解析")[正文。]', rendered.typst)

    def test_unumbered_question_falls_back_to_a_counter(self):
        rendered = render_handout(
            "## 一节\n\n求 $x$。\n\n"
            "<details>\n<summary>答案</summary>\n\n$x=1$。\n</details>\n"
        )
        self.assertIn("#selftest(1)[求 $x$。]", rendered.typst)


class TestFillInSelfTest(unittest.TestCase):
    def test_fill_in_link_renders_the_same_devices(self):
        draft = (
            "## 六、自测题\n\n"
            "**1.** 求 $L^{-1}[e^{-2s}/(s+3)]$。\n\n"
            "<details>\n<summary>答案</summary>\n\n"
            "先算 $L^{-1}[1/(s+3)]=e^{-3t}$。\n\n"
            "</details>\n"
        )
        typst = render_typst(draft).typst
        self.assertIn("#selftest(1)[求 ", typst)
        self.assertIn('#answer("答案")[先算 ', typst)
        self.assertNotIn("<details>", typst)
        self.assertNotIn("<summary>", typst)


class TestMathrmWithNestedCommands(unittest.TestCase):
    """`\\mathrm{\\mu F}` 里的 `\\mu` 要转成符号，不能印成字面量 `\\mu`。"""

    def test_mu_inside_mathrm_is_converted(self):
        converted, _warnings = latex_to_typst("\\mathrm{\\mu F}")
        self.assertEqual(converted, "upright(mu F)")
        self.assertNotIn("\\mu", converted)

    def test_conversion_stays_idempotent(self):
        converted, _warnings = latex_to_typst("\\mathrm{\\Omega}")
        self.assertEqual(latex_to_typst(converted)[0], converted)


class TestTemplatesDefineTheDevices(unittest.TestCase):
    def _read(self, relative: str) -> str:
        with open(os.path.join(ROOT, relative), encoding="utf-8") as handle:
            return handle.read()

    def test_reading_template(self):
        text = self._read(os.path.join("zju_lecture", "handout_prelude.typ"))
        self.assertIn("#let selftest(number, body)", text)
        self.assertIn("#let answer(label, body)", text)

    def test_fill_in_prelude(self):
        text = self._read(os.path.join("zju_lecture", "prelude.typ"))
        self.assertIn("#let selftest(number, body)", text)
        self.assertIn("#let answer(label, body)", text)


if __name__ == "__main__":
    unittest.main()
