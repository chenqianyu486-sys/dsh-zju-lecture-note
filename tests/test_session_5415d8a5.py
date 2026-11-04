# -*- coding: utf-8 -*-
"""实地会话 session-5415d8a5 暴露的「与 LLM 打架」回归。

2026-11-04 的一次真实课程（sub_id 1990907，大学物理·麦克斯韦方程组）里，
插件本身能跑通，但 Agent 花了大量步数在**替工具擦屁股**：

1. ``\\qquad`` 被映射成两个空格，Typst 把空格折叠掉 → 四条麦克斯韦方程
   挤成 ``0∇×H`` 这种像乘法的东西。Agent 自己写了 ``.tmp_split_display.py``
   把 28 个公式块拆开，再重排两份 PDF。
2. 行内 ``$1/r$`` 被 Typst 排成竖着的分式，把行距顶高；Agent 手改 4 处
   成 ``r^{-1}``。
3. 讲义抬头的多行引用块在 PDF 里印成字面量 ``>``，字段还粘成一句
   「时长：约 01:40:16 上课时间：未提供…」；Agent 把引用块手改成普通段落
   （两份文件、4 次编辑）。
4. ``bare_imaginary_unit`` 把 LC 回路里的**电流** ``i`` 报成虚数单位，
   Agent 改了 3 处 ``i → I`` 并多排一轮 PDF。
5. 方框预算按 h2 统计，7 个 ``### 2.x`` 小节各 1–2 个框被算成「9 个超预算」。
6. 填空挖空是十几处精确替换，一条一条调用编辑工具 → 12 次往返。

本文件按条钉住，避免以后被改回去。
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import mcp_server  # noqa: E402
from zju_lecture import handout  # noqa: E402
from zju_lecture.note_lint import check_markdown  # noqa: E402
from zju_lecture.study_notes import (  # noqa: E402
    apply_draft_edits,
    build_draft,
    find_typst,
    latex_to_typst,
    render_typst,
)


HEADER_NOTE = """# 课程知识总结：电磁场与电磁波

> **来源**：智云课堂 (sub_id: `1990907`, course_id: `87570`) | **时长**：约 `01:40:16`
> **上课时间**：未提供（课堂原话提到「上周五」「13 号考试」，未给出绝对日期，故不填）
> **本节定位**：第 15 章收尾——把前面分散的静电场、静磁场、电磁感应四套规律合成麦克斯韦方程组，
> 引入位移电流，推出电磁波，讨论能量传输、偶极辐射、LC 振荡电路与赫兹实验。

> ⚠ **ASR 说明**：本讲义由语音字幕整理，ASR 可靠度「低」（噪声比 11.3%、碎句比 11%、
> 高频口头禅「这个」×405 /「就是」×350 /「对吧」×308）。`[00:06]`–`[00:09]` 处的原字幕
> 不可直读，相关式子已按电动力学标准规范**重新推导校核**，请对照视频复核推导细节。

## 一、本课速览

正文里行内 $1/r$ 不该把行距顶高。

$$
\\nabla\\cdot\\mathbf{E} = \\frac{\\rho}{\\varepsilon_0}
\\qquad
\\nabla\\times\\mathbf{E} = -\\frac{\\partial \\mathbf{B}}{\\partial t}
$$
"""


class TestDisplaySpacing(unittest.TestCase):
    """`\\qquad` / `\\quad` 要排成真正的间距，不是被折叠掉的空格。"""

    def test_qquad_becomes_a_typst_wide_space(self):
        converted, warnings = latex_to_typst(
            r"\nabla\cdot\mathbf{B} = 0 \qquad \nabla\times\mathbf{H} = \mathbf{J}"
        )
        self.assertIn("wide", converted)
        self.assertEqual(warnings, [])
        # 两个空格会被 Typst 折叠，等于没加间距。
        self.assertNotIn("  ", converted)

    def test_quad_becomes_a_typst_quad_space(self):
        converted, _ = latex_to_typst(r"a \quad b")
        self.assertIn("quad", converted)

    def test_thin_and_medium_spaces_survive(self):
        self.assertIn("thin", latex_to_typst(r"a\,b")[0])
        self.assertIn("med", latex_to_typst(r"a\;b")[0])

    def test_conversion_is_idempotent(self):
        once = latex_to_typst(r"a \qquad b \quad c")[0]
        twice = latex_to_typst(once)[0]
        self.assertEqual(once, twice)

    def test_handout_keeps_the_gap(self):
        rendered = handout.render_handout(HEADER_NOTE, title="电磁场与电磁波")
        self.assertIn("wide", rendered.typst)
        self.assertNotIn("qquad", rendered.typst)
        self.assertEqual(rendered.warnings, [])


class TestInlineSlash(unittest.TestCase):
    """行内 `a/b` 保持平排；块级公式仍然排成分式。"""

    def test_inline_slash_stays_flat(self):
        converted, _ = latex_to_typst("1/r", inline=True)
        self.assertEqual(converted, "1 slash r")

    def test_display_slash_still_makes_a_fraction(self):
        converted, _ = latex_to_typst("1/r")
        self.assertEqual(converted, "1/r")

    def test_quoted_text_is_not_touched(self):
        converted, _ = latex_to_typst(r"\text{m/s}", inline=True)
        self.assertEqual(converted, 'upright("m/s")')

    def test_handout_inline_math_is_flat(self):
        rendered = handout.render_handout(HEADER_NOTE, title="电磁场与电磁波")
        self.assertIn("1 slash r", rendered.typst)

    def test_draft_renderer_keeps_display_and_inline_apart(self):
        rendered = render_typst("行内 $1/r$ 平排。\n\n$ 1/r $\n")
        self.assertIn("1 slash r", rendered.typst)
        # 独占一行的公式仍然排上下分式（`$ 1/r $`）。
        self.assertIn("1/r", rendered.typst)


class TestQuoteBlocks(unittest.TestCase):
    """`>` 引用块：Typst 没有这个语法，必须走内容块；字段之间不能粘连。"""

    def test_fill_in_note_uses_a_real_block(self):
        draft = build_draft(HEADER_NOTE, title="电磁场与电磁波")
        rendered = render_typst(draft.text)
        self.assertIn("#quoted[", rendered.typst)
        for line in rendered.typst.split("\n"):
            self.assertFalse(
                line.lstrip().startswith(">"),
                "Typst 的引用块不能靠行首 `>`：会被当成字面量印出来",
            )

    def test_header_fields_are_separated(self):
        rendered = render_typst(build_draft(HEADER_NOTE, title="电磁场与电磁波").text)
        block = rendered.typst[rendered.typst.index("#quoted["):]
        block = block[: block.index("]")]
        # 三个字段各占一行：行尾用 Typst 的反斜杠换行，共两处。
        backslash = chr(92)
        self.assertEqual(block.count(backslash + "\n"), 2)
        self.assertNotIn("01:40:16*上课时间*", block.replace("\n", ""))

    def test_reading_pdf_separates_the_same_fields(self):
        rendered = handout.render_handout(HEADER_NOTE, title="电磁场与电磁波")
        self.assertIn("#linebreak()*上课时间*", rendered.typst)
        self.assertNotIn("> **来源**", rendered.typst)

    def test_wrapped_asr_paragraph_is_joined(self):
        draft = build_draft(HEADER_NOTE, title="电磁场与电磁波")
        rendered = render_typst(draft.text)
        # 软换行的两行接成一句（中文之间不补空格），不该出现行中断。
        self.assertIn("碎句比 11%、高频口头禅", rendered.typst)

    def test_compiles_when_typst_is_available(self):
        if not find_typst():
            self.skipTest("本机没有 Typst")
        from zju_lecture.study_notes import compile_project

        rendered = render_typst(build_draft(HEADER_NOTE, title="电磁场与电磁波").text)
        work = tempfile.mkdtemp()
        try:
            result = compile_project(work, rendered.typst, make_png=False)
            self.assertTrue(result.ok, result.errors)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class TestBoxBudgetPerSubsection(unittest.TestCase):
    """每节预算按**最小**小节算，不把 7 个小节合成一节。"""

    NOTE = (
        "# 标题\n\n## 二、分章详解\n\n"
        "### 2.1 甲\n\n[定义] a —— b\n\n[定理] c —— d\n\n"
        "### 2.2 乙\n\n[定义] e —— f\n\n[定理] g —— h\n\n"
        "### 2.3 丙\n\n[例] i —— j\n"
    )

    def test_fill_in_note_does_not_flag_subsections(self):
        rendered = render_typst(self.NOTE)
        self.assertFalse(
            [item for item in rendered.warnings if "视觉预算" in item],
            rendered.warnings,
        )

    def test_reading_pdf_does_not_flag_subsections(self):
        rendered = handout.render_handout(self.NOTE, title="标题")
        self.assertFalse(
            [item for item in rendered.warnings if "视觉预算" in item],
            rendered.warnings,
        )

    def test_a_single_subsection_with_three_boxes_is_flagged(self):
        note = "### 2.1 甲\n\n[定义] a —— b\n\n[定理] c —— d\n\n[例] e —— f\n"
        rendered = render_typst(note)
        self.assertTrue(
            [item for item in rendered.warnings if "视觉预算" in item],
            rendered.warnings,
        )


class TestImaginaryUnitIsNotCurrent(unittest.TestCase):
    """物理课里的 `i` 多半是电流，不能见到就报虚数单位。"""

    def _flags(self, text):
        return [
            issue
            for issue in check_markdown(text + "\n")
            if issue.code == "bare_imaginary_unit"
        ]

    def test_lc_circuit_current_is_not_flagged(self):
        self.assertFalse(self._flags(
            r"解 $q = q_0\cos(\omega_0 t+\varphi)$，$i = -q_0\omega_0\sin(\omega_0 t)$。"
        ))

    def test_phase_difference_sentence_is_not_flagged(self):
        self.assertFalse(self._flags(r"注意 $q$ 与 $i$ 相位差 $\pi/2$。"))

    def test_current_as_function_of_time_is_not_flagged(self):
        self.assertFalse(self._flags(r"电流 $i(t)$ 随时间变化。"))

    def test_square_of_i_is_still_flagged(self):
        self.assertTrue(self._flags(r"由 $i^2 = -1$ 得"))

    def test_complex_context_word_triggers_the_warning(self):
        self.assertTrue(self._flags(r"复数的虚部：$z = a + i b$ 中的 b"))


class TestBatchPatch(unittest.TestCase):
    """`mode=patch`：把十几处挖空一次写回。"""

    def test_applies_matches_in_order(self):
        result = apply_draft_edits("甲。乙。丙。", [
            {"old": "乙", "new": "____"},
            {"old": "丙", "new": "丁"},
        ])
        self.assertEqual(result.applied, 2)
        self.assertEqual(result.text, "甲。____。丁。")
        self.assertEqual(result.failures, [])

    def test_missing_text_is_reported_not_fatal(self):
        result = apply_draft_edits("甲。", [{"old": "找不到", "new": "x"}])
        self.assertEqual(result.applied, 0)
        self.assertEqual(result.text, "甲。")
        self.assertEqual(len(result.failures), 1)
        self.assertIn("未找到", result.failures[0])

    def test_ambiguous_text_needs_all(self):
        result = apply_draft_edits("a a b", [{"old": "a", "new": "z"}])
        self.assertEqual(result.applied, 0)
        self.assertIn("出现 2 次", result.failures[0])
        replaced = apply_draft_edits("a a b", [{"old": "a", "new": "z", "all": True}])
        self.assertEqual(replaced.text, "z z b")

    def test_noop_edits_are_skipped(self):
        result = apply_draft_edits("甲。", [{"old": "甲", "new": "甲"}])
        self.assertEqual(result.applied, 0)
        self.assertEqual(result.skipped, 1)

    def test_tool_schema_advertises_patch(self):
        tool = next(t for t in mcp_server.TOOLS if t["name"] == "zju_build_study_notes")
        self.assertIn("patch", tool["inputSchema"]["properties"]["mode"]["enum"])
        self.assertIn("edits", tool["inputSchema"]["properties"])


class TestPatchTool(unittest.TestCase):
    """工具层的 patch 模式：写回文件、报告失败、给出下一步。"""

    def setUp(self):
        self.workspace = tempfile.mkdtemp()
        self.previous = os.environ.get("ZJU_WORKSPACE")
        os.environ["ZJU_WORKSPACE"] = self.workspace
        self.draft = os.path.join(self.workspace, "知识总结-测试-填空底稿.md")
        with open(self.draft, "w", encoding="utf-8") as handle:
            handle.write("总电流连续。辐射功率正比于频率的四次方。")

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("ZJU_WORKSPACE", None)
        else:
            os.environ["ZJU_WORKSPACE"] = self.previous
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_patch_writes_the_file(self):
        report = mcp_server._dispatch_tool("zju_build_study_notes", {
            "mode": "patch",
            "draft_path": self.draft,
            "edits": [{"old": "连续", "new": "____"}],
        })
        self.assertIn("应用: 1/1", report)
        with open(self.draft, encoding="utf-8") as handle:
            self.assertIn("总电流____", handle.read())

    def test_patch_reports_failures_and_still_saves_the_rest(self):
        report = mcp_server._dispatch_tool("zju_build_study_notes", {
            "mode": "patch",
            "draft_path": self.draft,
            "edits": [
                {"old": "连续", "new": "____"},
                {"old": "不存在", "new": "x"},
            ],
        })
        self.assertIn("应用: 1/2", report)
        self.assertIn("未应用 1 处", report)
        self.assertIn("compile", report)

    def test_patch_requires_edits(self):
        report = mcp_server._dispatch_tool(
            "zju_build_study_notes", {"mode": "patch", "draft_path": self.draft}
        )
        self.assertIn("edits", report)

    def test_patch_requires_draft_path(self):
        report = mcp_server._dispatch_tool(
            "zju_build_study_notes", {"mode": "patch", "edits": []}
        )
        self.assertIn("draft_path", report)


if __name__ == "__main__":
    unittest.main()
