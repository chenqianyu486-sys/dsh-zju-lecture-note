# -*- coding: utf-8 -*-
"""实地会话 session-d0cfd0ac 暴露的矛盾点回归。

2026-11-03 的一次真实课程（sub_id 1990049，89 步）里，约 50 步在跟「填空底稿」
打架。逐条还原成测试，避免以后又被改回去：

1. **底稿里全是 Typst 数学，文档却说「公式写 LaTeX」**：
   `build_draft` 已经把 `\\sum_{n=1}` 转成 `sum_(n = 1)`，模型按文档继续写 LaTeX，
   第二次转换把 `frac(…)` / `cal(…)` 逐字母拆成 `f r a c` / `c a l`，
   编译报 `unknown variable: Res`。
2. **表格被写成 `#table(…)` 塞进 Markdown**：`render_typst` 不认表格，
   把 `#table(` 那一行当正文转义成 `\\[a\\]`，PDF 里就是一堆带反斜杠的方括号。
3. **行内代码被转义**：`` `[00:20]` `` 变成 `` `\\[00:20\\]` ``，PDF 里原样印出反斜杠。
4. **`**加粗**` 没转**：Typst 报 `warning: no text within stars`，加粗失效。
5. **转不动的命令只在 PDF 阶段炸**：`\\triangleq` 让整份 PDF 失败，而
   Markdown 规范检查同时报「通过 —— 未发现问题」。
6. **PDF 落在 `*-typst/out.pdf`**：Agent 每次都要手动 `cp` 才交得出来。
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mcp_server  # noqa: E402
from zju_lecture.note_lint import check_markdown  # noqa: E402
from zju_lecture.study_notes import (  # noqa: E402
    build_draft,
    find_typst,
    latex_to_typst,
    render_typst,
)

NOTE = """# 复变函数 第 3 讲 留数定理

## 一、留数的定义

设 $f(z)$ 在孤立奇点 $z_0$ 处的 Laurent 展开为

$$
\\sum_{n=-\\infty}^{\\infty} a_n (z-z_0)^n
$$

则留数定义为 $a_{-1}$。记作 $\\operatorname{Res}(f, z_0) \\triangleq a_{-1}$。

| 性质 | 时域 | 象函数 |
| :--- | :--- | :--- |
| 平移 | 乘 $u(t-t_0)$ | 乘 $e^{-s t_0}$ |
| 积分 | $\\int_0^t f$ | $\\frac{F(s)}{s}$ |

复现步骤（时间点 `[00:20]`）：

1. 先找奇点；
2. 再算留数；
3. 最后求和。

**注意**：$\\lim_{s \\to \\infty} F(s) = 0$ 是留数法的前提。

## 二、留数定理

[定义] 留数定理 —— 设 $f$ 在简单闭曲线 $C$ 内除有限个孤立奇点外解析。

$$
\\oint_C f(z) \\, dz = 2\\pi i \\sum_k \\operatorname{Res}(f, z_k)
$$
"""


class TestMathConversionIsIdempotent(unittest.TestCase):
    """转换器必须能吃掉自己的输出（否则二次转换毁公式）。"""

    CASES = [
        r"\sum_{n=1}^{\infty}\frac{a_n}{s^n}",
        r"\mathcal{L}[e^{-st}]",
        r"a\quad b",
        r"\operatorname{Res}[F(s)e^{st}, s_k]",
        r"\int_0^{t} f(\tau)\,\mathrm{d}\tau",
        r"\lim_{s \to \infty} F(s) = 0",
        r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}",
    ]

    def test_second_pass_is_a_no_op(self):
        for latex in self.CASES:
            with self.subTest(latex=latex):
                once, _ = latex_to_typst(latex)
                twice, _ = latex_to_typst(once)
                self.assertEqual(once, twice, f"{latex} 二次转换被改写：{twice!r}")

    def test_converter_output_is_never_letter_split(self):
        once, _ = latex_to_typst(r"\sum_{n=1}^{\infty}\frac{a_n}{s^n}")
        self.assertIn("sum_", once)
        self.assertIn("frac(", once)
        for bad in ("s u m", "f r a c", "c a l"):
            self.assertNotIn(bad, latex_to_typst(once)[0])

    def test_quoted_operator_name_is_not_rewrapped(self):
        once, _ = latex_to_typst(r"\operatorname{Res}[F(s)]")
        self.assertIn('"Res"', once)
        self.assertNotIn("upright(", latex_to_typst(once)[0])


class TestDraftKeepsMarkdown(unittest.TestCase):
    """`mode=draft` 只搬运结构：公式/表格/列表/行内代码都保持 Markdown。"""

    def setUp(self):
        self.draft = build_draft(NOTE).text

    def test_math_stays_latex(self):
        self.assertIn("\\sum_{n=-\\infty}^{\\infty}", self.draft)
        self.assertNotIn("sum_(n = -∞)", self.draft)
        self.assertNotIn("frac(", self.draft)
        self.assertNotIn("cal(", self.draft)

    def test_table_stays_gfm(self):
        self.assertNotIn("#table(", self.draft)
        self.assertTrue(
            any(line.strip().startswith("|") for line in self.draft.splitlines())
        )

    def test_ordered_list_stays_markdown(self):
        self.assertIn("\n1. 先找奇点", self.draft)

    def test_inline_code_is_untouched(self):
        self.assertIn("`[00:20]`", self.draft)


class TestRenderSupportsMarkdown(unittest.TestCase):
    """`mode=compile` 是唯一转换点，且要把 Markdown 结构映射到 Typst。"""

    def setUp(self):
        self.typst = render_typst(build_draft(NOTE).text).typst

    def test_latex_is_converted_once(self):
        self.assertIn("sum_(n = -∞)", self.typst)
        self.assertNotIn("\\sum", self.typst)

    def test_table_becomes_a_typst_table(self):
        self.assertIn("#table(", self.typst)
        self.assertNotIn("\\[a\\]", self.typst)

    def test_lists_are_typst_lists(self):
        self.assertIn("+ 先找奇点", self.typst)

    def test_inline_code_is_not_escaped(self):
        self.assertIn("`[00:20]`", self.typst)
        self.assertNotIn("`\\[00:20\\]`", self.typst)

    def test_bold_is_converted(self):
        self.assertIn("*注意*", self.typst)
        self.assertNotIn("**注意**", self.typst)


class TestUnsupportedCommands(unittest.TestCase):
    """`\\triangleq` 这类命令：要么有映射，要么在 Markdown 检查里点名。"""

    def test_definition_symbol_has_a_mapping(self):
        self.assertEqual(latex_to_typst(r"a \triangleq b")[0], "a ≙ b")
        self.assertEqual(latex_to_typst(r"a \triangleq b")[1], [])

    def test_not_is_negated_not_printed_as_a_word(self):
        self.assertEqual(latex_to_typst(r"F(s) \not\to 0")[0], "F(s) ↛ 0")
        self.assertEqual(latex_to_typst(r"x \not= y")[0], "x ≠ y")

    def test_unmapped_command_is_named_by_lint(self):
        issues = check_markdown("## 一\n\n设 $x \\overset{a}{=} y$。\n")
        codes = {issue.code for issue in issues}
        self.assertIn("latex_unmapped", codes)
        message = " ".join(issue.message for issue in issues)
        self.assertIn("\\overset", message)

    def test_unmapped_command_in_display_block_is_named(self):
        issues = check_markdown("## 一\n\n$$\n\\underset{x}{=}\n$$\n")
        self.assertIn("latex_unmapped", {issue.code for issue in issues})

    def test_supported_commands_are_not_flagged(self):
        issues = check_markdown(
            "## 一\n\n"
            r"设 $a \triangleq b$，$F(s) \not\to 0$，$\frac{1}{s}$，$\mathcal{L}[f]$。"
            "\n"
        )
        self.assertEqual([issue.code for issue in issues if issue.code == "latex_unmapped"], [])

    def test_lint_never_flags_a_convertible_command(self):
        # `\sqrt` 曾经漏在命令表外：PDF 明明排得出来，检查却报「没有 Typst 写法」。
        # 命令表必须和转换器的分支一一对齐，这里用一组代表性命令守。
        samples = [
            r"\sqrt{x}", r"\frac{a}{b}", r"\triangleq", r"\not=",
            r"\operatorname{Res}", r"\mathcal{L}", r"\mathbb{R}",
            r"\overline{z}", r"\vec{v}", r"\begin{pmatrix}a\end{pmatrix}",
            r"\left(x\right)", r"\text{当}", r"\sin x", r"\sum_{n=1}^{\infty}",
            r"\int_0^1 f", r"\lim_{x\to0}", r"\quad",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                issues = check_markdown("## 一\n\n公式 ${}$。\n".format(sample))
                self.assertNotIn(
                    "latex_unmapped",
                    {issue.code for issue in issues},
                    f"{sample} 被误报成不可转换",
                )


class TestStudyNotesPdfSitsNextToTheDraft(unittest.TestCase):
    """PDF 要落在底稿同目录，别再让 Agent `cp` 一次。"""

    def setUp(self):
        self.workspace = tempfile.mkdtemp()
        self.previous = os.environ.get("ZJU_WORKSPACE")
        os.environ["ZJU_WORKSPACE"] = self.workspace

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("ZJU_WORKSPACE", None)
        else:
            os.environ["ZJU_WORKSPACE"] = self.previous
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_compile_writes_a_sibling_pdf(self):
        if not find_typst():
            self.skipTest("本机没有 typst，跳过编译测试")
        note = os.path.join(self.workspace, "知识总结-2026-11-03-复变函数-留数.md")
        with open(note, "w", encoding="utf-8") as handle:
            handle.write(NOTE)
        # 阅读版 PDF 先放一个哨兵：填空链路不得覆盖它。
        reading_pdf = os.path.join(self.workspace, "知识总结-2026-11-03-复变函数-留数.pdf")
        with open(reading_pdf, "wb") as handle:
            handle.write(b"reading-pdf-sentinel")
        mcp_server._dispatch_tool(
            "zju_build_study_notes", {"mode": "draft", "note_path": note}
        )
        draft = os.path.join(self.workspace, "知识总结-2026-11-03-复变函数-留数-填空底稿.md")
        report = mcp_server._dispatch_tool(
            "zju_build_study_notes",
            {"mode": "compile", "draft_path": draft, "make_png": False},
        )
        self.assertIn("PDF:", report)
        # 不能和阅读版那份 `<讲义名>.pdf` 撞名 —— 撞了会把阅读版覆盖掉。
        sibling = os.path.join(self.workspace, "知识总结-2026-11-03-复变函数-留数-填空.pdf")
        self.assertTrue(os.path.exists(sibling), report)
        self.assertIn(sibling, report)
        with open(reading_pdf, "rb") as handle:
            self.assertEqual(handle.read(), b"reading-pdf-sentinel",
                             "填空笔记覆盖了阅读版 PDF")


if __name__ == "__main__":
    unittest.main()
