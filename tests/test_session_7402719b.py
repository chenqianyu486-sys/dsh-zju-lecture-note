# -*- coding: utf-8 -*-
"""实地会话 session-7402719b 暴露的多余手工操作回归。

2026-11-04 的一次真实课程（sub_id 1990907，大学物理·麦克斯韦方程组）里，
Agent 为了绕过工具缺口做了不少本不该有的手工修正：

1. ``\\perp`` / ``\\leftrightarrow`` 没映射，``zju_write_note`` 直接
   ``PDF 跳过: error: unknown variable: leftrightarrow``，Agent 手改 Markdown。
2. ``$L\\frac{\\mathrm{d}i}{\\mathrm{d}t}$`` 被 ``bare_imaginary_unit`` 误报，
   Agent 差点把「电流 i」改成 ``\\mathrm{i}``（物理量就错了）。
3. ``build_draft`` 每节插三条空占位，Agent 删改近 20 次。
4. ``---`` 在填空笔记里被排成孤立「–」，Agent 写通配脚本删分隔线，误伤旧讲义。
5. ``\\partial D/\\partial t`` 这类斜杠分式渲染不理想，Agent 写脚本逐条替换。
6. 用户要求小节标题后的间距再大一些。

本文件按条钉住，避免以后被改回去。
"""

import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zju_lecture import handout  # noqa: E402
from zju_lecture.note_lint import check_markdown  # noqa: E402
from zju_lecture.study_notes import (  # noqa: E402
    build_draft,
    compile_project,
    find_typst,
    latex_to_typst,
    render_typst,
)

NOTE = r"""# 大学物理 第 15 章 麦克斯韦方程组

## 一、位移电流

电磁波是横波，$E \perp H$，且 $E \times H$ 指向传播方向。

弹簧振子类比：把 $q \leftrightarrow x$、$L \leftrightarrow m$。

电流与电荷满足 $L\frac{\mathrm{d}i}{\mathrm{d}t} + \frac{q}{C} = 0$。

---

## 二、波动方程

由 $\partial D/\partial t$ 与 $\partial B_z/\partial x$ 得
$\sqrt{\mu_0/\varepsilon_0}$ 就是光速。
"""


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


class TestRelationSymbols(unittest.TestCase):
    """\\perp / \\leftrightarrow 必须能转，且不能再报 latex_unmapped。"""

    def test_perp_and_leftrightarrow_are_mapped(self):
        self.assertEqual(latex_to_typst(r"E \perp H")[0], "E ⊥ H")
        self.assertEqual(latex_to_typst(r"q \leftrightarrow x")[0], "q ↔ x")
        for latex in (r"E \perp H", r"q \leftrightarrow x"):
            converted, issues = latex_to_typst(latex)
            self.assertEqual(issues, [], latex)
            self.assertEqual(latex_to_typst(converted)[0], converted)

    def test_lint_no_longer_calls_them_unmapped(self):
        issues = check_markdown(
            r"正交：$E \perp H$；类比：$q \leftrightarrow x$。"
        )
        self.assertFalse(
            [issue for issue in issues if issue.code == "latex_unmapped"],
            issues,
        )


class TestImaginaryUnitIsNotCurrent(unittest.TestCase):
    """\\mathrm{d}i 里的 i 是电流，不该被当成虚数单位。"""

    def test_derivative_current_is_not_flagged(self):
        issues = check_markdown(r"$L\frac{\mathrm{d}i}{\mathrm{d}t} + \frac{q}{C} = 0$")
        self.assertFalse(
            [issue for issue in issues if issue.code == "bare_imaginary_unit"],
            issues,
        )

    def test_real_imaginary_unit_is_still_flagged(self):
        issues = check_markdown(r"$i^2 = -1$")
        self.assertTrue(
            [issue for issue in issues if issue.code == "bare_imaginary_unit"],
            issues,
        )


class TestSlashFractions(unittest.TestCase):
    """明确的微分/根式斜杠分式在渲染层归一化，不改普通 a/b。"""

    def test_partial_slash_becomes_frac(self):
        converted, issues = latex_to_typst(r"\partial D/\partial t")
        self.assertEqual(converted, "frac(∂ D, ∂ t)")
        self.assertEqual(issues, [])
        self.assertEqual(latex_to_typst(converted)[0], converted)

    def test_differential_slash_becomes_frac(self):
        converted, issues = latex_to_typst(r"\mathrm{d}i/\mathrm{d}t")
        self.assertIn("frac(", converted)
        self.assertNotIn("/", converted)
        self.assertEqual(issues, [])

    def test_sqrt_slash_becomes_frac(self):
        converted, issues = latex_to_typst(r"\sqrt{\mu_0/\varepsilon_0}")
        self.assertEqual(converted, "sqrt(frac(mu_0, epsilon_0))")
        self.assertEqual(issues, [])
        self.assertEqual(latex_to_typst(converted)[0], converted)

    def test_ordinary_slash_is_left_alone(self):
        # 单位 m/s、普通除法 a/b 不在自动转换范围里。
        self.assertEqual(latex_to_typst("m/s")[0], "m/s")
        self.assertEqual(latex_to_typst("a/b")[0], "a/b")


class TestDraftSkeleton(unittest.TestCase):
    """骨架只搬运原文，不再逐节塞空占位。"""

    def setUp(self):
        self.draft = build_draft(NOTE, author="测试", date="2026-11-04")

    def test_no_boilerplate_placeholders(self):
        text = self.draft.text
        for phrase in (
            "（用一句人话解释",
            "留给读者自己重做",
            "一个主动回忆问题",
            "本节有公式",
        ):
            self.assertNotIn(phrase, text)
        self.assertIn("可选装置", text)

    def test_no_active_marker_lines(self):
        marker_lines = [
            line.strip()
            for line in self.draft.text.splitlines()
            if line.strip().startswith("[")
        ]
        self.assertEqual(marker_lines, [])

    def test_existing_content_survives(self):
        text = self.draft.text
        self.assertIn(r"E \perp H", text)
        self.assertIn(r"q \leftrightarrow x", text)
        self.assertIn("---", text)

    def test_compile_still_works(self):
        if not find_typst():
            self.skipTest("本机没有 typst，跳过编译测试")
        rendered = render_typst(self.draft.text)
        self.assertIn("#divider", rendered.typst)
        with tempfile.TemporaryDirectory() as directory:
            result = compile_project(directory, rendered.typst, make_png=False)
            self.assertTrue(result.ok, result.errors)


class TestHorizontalRule(unittest.TestCase):
    """`---` 必须映射成细分隔线，不能留下一个孤立「–」。"""

    def test_fill_in_pipeline_maps_hr_to_divider(self):
        rendered = render_typst("## 一节\n\n正文。\n\n---\n\n下一段。")
        self.assertIn("#divider", rendered.typst)
        self.assertNotIn("---", rendered.typst)
        self.assertEqual(rendered.devices.get("divider"), 1)

    def test_reading_pipeline_maps_hr_to_divider(self):
        with tempfile.TemporaryDirectory() as directory:
            out = handout.render_handout(
                "## 一节\n\n正文。\n\n---\n\n下一段。",
                workspace_root=directory,
                note_path=os.path.join(directory, "note.md"),
                toc=False,
            )
        self.assertIn("#divider", out.typst)
        self.assertNotIn("---", out.typst)


class TestHeadingSpacing(unittest.TestCase):
    """小节标题后的间距加大，两条链路一致（规范见 typography-spec.md）。"""

    def test_reading_template(self):
        text = read(os.path.join(ROOT, "zju_lecture", "handout_prelude.typ"))
        self.assertIn("above: 20pt, below: 12pt", text)
        self.assertIn("block(above: 12pt, below: 0.85em)", text)
        self.assertIn("block(above: 9pt, below: 0.65em)", text)

    def test_vendored_template_and_patch(self):
        lib = read(
            os.path.join(
                ROOT, "zju_lecture", "typst-packages", "preview", "scholia", "0.1.0",
                "src", "lib.typ",
            )
        )
        self.assertIn("block(above: 20pt, below: 12pt, width: 100%)", lib)
        self.assertIn("block(above: 12pt, below: 0.85em)", lib)
        self.assertIn("block(above: 9pt, below: 0.65em)", lib)

        patch_tool = read(os.path.join(ROOT, "tools", "vendor_typst_packages.py"))
        self.assertIn("below: 12pt, width: 100%", patch_tool)
        self.assertIn("below: 0.85em", patch_tool)
        self.assertIn("below: 0.65em", patch_tool)


class TestVersion(unittest.TestCase):
    def test_package_and_server_versions_match(self):
        # 只要求「两处一致」；具体版本号由 release 流程改，不在这里写死
        # （写死过 2.2.2，结果 2.2.3 一升级这条就红）。
        with io.open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            version = json.load(handle)["version"]
        self.assertIn(
            'SERVER_VERSION = "' + version + '"',
            read(os.path.join(ROOT, "mcp_server.py")),
        )


if __name__ == "__main__":
    unittest.main()
