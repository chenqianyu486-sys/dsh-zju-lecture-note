# -*- coding: utf-8 -*-
"""v1.6.0 填空式学习笔记链路回归：讲义 → 填空底稿 → Typst → PDF。

守的是三条容易悄悄坏掉的规则：

1. **底稿语法是受限的**，渲染必须严格按 arity 生成 knot —— 多给一个内容块
   不会报错，只会被渲染成小字标签（这正是 skill 自己写的「必须看 PNG」）。
2. **Typst markup 有转义规则**：``_`` ``\\`` ``[`` ``#`` ``@`` 在底稿里是字面量，
   不转义就会渲染成别的东西（斜体、丢失、引用报错）。
3. **许可与归属随包分发**：Skill 目录必须带自己的 LICENSE 与
   THIRD_PARTY_NOTICES，且 prelude 的生成副本必须与权威副本逐字节一致。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import mcp_server  # noqa: E402
from zju_lecture.study_notes import (  # noqa: E402
    StudyNotesError,
    build_draft,
    compile_project,
    find_typst,
    latex_to_typst,
    render_typst,
)

NOTE = """# 复变函数 第 3 讲 留数定理

## 一、留数的定义

设 $f(z)$ 在孤立奇点 $z_0$ 处的 Laurent 展开为

$$\\sum_{n=-\\infty}^{\\infty} a_n (z-z_0)^n$$

则留数定义为 $a_{-1}$。

## 二、留数定理

$$\\oint_C f(z) \\, dz = 2\\pi i \\sum_k \\operatorname{Res}(f, z_k)$$
"""


class TestLatexToTypst(unittest.TestCase):
    """LaTeX 数学 → Typst 数学。"""

    def test_fraction(self):
        self.assertEqual(latex_to_typst(r"\frac{a}{b}")[0], "frac(a, b)")
        self.assertEqual(latex_to_typst(r"\dfrac{a}{b}")[0], "frac(a, b)")

    def test_sqrt_and_root(self):
        self.assertEqual(latex_to_typst(r"\sqrt{x}")[0], "sqrt(x)")
        self.assertEqual(latex_to_typst(r"\sqrt[3]{x}")[0], "root(3, x)")

    def test_scripts_split_multi_letter_identifiers(self):
        # `a_(ij)` 在 Typst 里是错的：ij 会被当成一个标识符。
        self.assertEqual(latex_to_typst("a_{ij}")[0], "a_(i j)")
        self.assertEqual(latex_to_typst("x^{2}")[0], "x^(2)")

    def test_script_content_is_converted_recursively(self):
        # 上下标里的 \infty 不转换的话，到 Typst 那里就是未知变量。
        self.assertEqual(latex_to_typst(r"a_{n=-\infty}")[0], "a_(n = -∞)")

    def test_operatorname_becomes_a_quoted_symbol(self):
        self.assertEqual(latex_to_typst(r"\operatorname{rank}(A)")[0], '"rank"(A)')

    def test_blackboard_bold(self):
        self.assertEqual(latex_to_typst(r"\mathbb{R}")[0], "RR")

    def test_differential_is_split(self):
        # `$dz$` 在 Typst 里是未知变量 dz；微分约定要写成 d z。
        self.assertIn("d z", latex_to_typst(r"\oint_C f(z) \, dz")[0])

    def test_ordinary_words_are_untouched(self):
        # diag 不该被当成微分符号拆开。
        self.assertEqual(latex_to_typst(r"\operatorname{diag}(A)")[0], '"diag"(A)')

    def test_unknown_command_is_reported_not_swallowed(self):
        converted, issues = latex_to_typst(r"\foo{x}")
        self.assertTrue(any("foo" in item for item in issues), issues)

    def test_sum_and_prod_map_to_typst_functions(self):
        self.assertEqual(latex_to_typst(r"\sum_{i=1}^n a_i")[0], "sum_(i = 1)^n a_i")
        self.assertEqual(latex_to_typst(r"\prod_{i=1}^n a_i")[0], "product_(i = 1)^n a_i")


class TestTypstEscaping(unittest.TestCase):
    """底稿里的字面量必须能安全地放进 Typst markup。"""

    def test_underscore_is_escaped(self):
        rendered = render_typst("普通段落 a_1 与 z_0。")
        self.assertIn("a\\_1", rendered.typst)
        self.assertIn("z\\_0", rendered.typst)

    def test_backslash_is_escaped(self):
        rendered = render_typst("路径 C:\\Users\\x")
        self.assertIn("C:\\\\Users\\\\x", rendered.typst)

    def test_brackets_are_escaped(self):
        rendered = render_typst("引用 [1] 结束")
        self.assertIn("\\[1\\]", rendered.typst)

    def test_hash_is_escaped(self):
        rendered = render_typst("C# 与 #1")
        self.assertIn("C\\#", rendered.typst)

    def test_email_is_not_treated_as_a_reference(self):
        rendered = render_typst("联系 someone@example.com 获取")
        self.assertNotIn("@example.com", rendered.typst.replace("\\@", ""))

    def test_known_reference_survives(self):
        rendered = render_typst("见 @def:term 的定义 <def:term>")
        self.assertIn("@def:term", rendered.typst)

    def test_helper_call_is_protected(self):
        rendered = render_typst("这里是 #mark-key[特征值] 术语")
        self.assertIn("#mark-key[特征值]", rendered.typst)


class TestBuildDraft(unittest.TestCase):
    """讲义 → 填空底稿。"""

    def setUp(self):
        self.draft = build_draft(NOTE, author="测试", date="2026-11-02")

    def test_cover_is_built_from_the_title(self):
        self.assertIn("# 封面", self.draft.text)
        self.assertIn("- title: 复变函数 第 3 讲 留数定理", self.draft.text)
        self.assertIn("- author: 测试", self.draft.text)

    def test_heading_is_not_duplicated(self):
        # 标题既作为章节行输出、又被当成正文行输出的话，PDF 里会出现两次。
        self.assertEqual(self.draft.text.count("## 一、留数的定义"), 1)
        self.assertEqual(self.draft.text.count("### 例"), 0)

    def test_cover_fields_do_not_leak_into_the_body(self):
        body = self.draft.text.split("## ", 1)[1]
        self.assertNotIn("- title:", body)
        self.assertNotIn("- author:", body)

    def test_markers_are_inserted(self):
        self.assertIn("[直觉]", self.draft.text)
        self.assertIn("[练习]", self.draft.text)
        self.assertIn("[边注]", self.draft.text)

    def test_math_is_kept_as_latex(self):
        # 底稿的契约是「纯 Markdown + LaTeX 数学」（format-spec.md §1）。
        # 公式在 build_draft 阶段**不改写**：转换只在 render_typst 里做一次，
        # 否则模型按文档继续写 LaTeX 时会被二次转换拆成 `f r a c`。
        self.assertIn(r"\sum_{n=-\infty}^{\infty}", self.draft.text)
        self.assertNotIn("sum_(n = -∞)", self.draft.text)
        self.assertNotIn("#table(", self.draft.text)

    def test_math_is_converted_at_render_time(self):
        rendered = render_typst(self.draft.text)
        self.assertIn("sum_(n = -∞)", rendered.typst)
        self.assertNotIn(r"\sum", rendered.typst)

    def test_sections_are_counted(self):
        self.assertEqual(self.draft.sections, 2)


class TestRenderTypst(unittest.TestCase):
    """底稿 → main.typ。"""

    def test_knot_arity_follows_frame_it_semantics(self):
        # frame-it：最后一个位置参数是正文，前面的是标题与标签。
        # 写成三块而以为是「标题+正文」，第二块会被渲染成小字标签且不报错。
        rendered = render_typst("[定义] 术语 —— 一句话说清对象")
        self.assertIn("#definition[术语][一句话说清对象]", rendered.typst)

    def test_knot_without_title_uses_one_block(self):
        rendered = render_typst("[定义] 一句话说清对象")
        self.assertIn("#definition[一句话说清对象]", rendered.typst)
        self.assertNotIn("#definition[一句话说清对象][", rendered.typst)

    def test_tagged_knot_uses_three_blocks(self):
        rendered = render_typst("[定理] 标题 | GSM 211, Thm 2.16 | 结论正文")
        self.assertIn("#theorem[标题][GSM 211, Thm 2.16][结论正文]", rendered.typst)

    def test_label_is_moved_out_of_the_body(self):
        rendered = render_typst("[定义] 术语 —— 正文 <def:term>")
        self.assertTrue(rendered.typst.rstrip().endswith("<def:term>"))
        self.assertNotIn("正文 <def:term>]", rendered.typst)

    def test_gap_becomes_a_todo(self):
        rendered = render_typst("[证明] (i) 甲 (ii) 乙 [缺口: 关键那一步]")
        self.assertIn("#TODO[关键那一步]", rendered.typst)

    def test_sidenote_uses_round_brackets(self):
        rendered = render_typst("[边注!] 看这里")
        self.assertIn("#sidenote([看这里], symbol: [!])", rendered.typst)

    def test_fillin_becomes_a_typst_helper(self):
        rendered = render_typst("定义里的挖空：____ 留在这里")
        self.assertIn("#fillin(width: 2.2cm)", rendered.typst)
        self.assertNotIn("\\_\\_\\_\\_", rendered.typst)

    def test_dangling_reference_is_reported(self):
        rendered = render_typst("见 @def:missing 的定义")
        self.assertTrue(any("missing" in item for item in rendered.warnings), rendered.warnings)

    def test_knot_budget_is_reported(self):
        draft = "\n".join(
            [
                "## 一节",
                "[定义] a —— b",
                "[定理] c —— d",
                "[例] e —— f",
                "[引理] g —— h",
            ]
        )
        rendered = render_typst(draft)
        self.assertTrue(any("视觉预算" in item for item in rendered.warnings), rendered.warnings)

    def test_dark_theme_does_not_inject_the_light_palette(self):
        rendered = render_typst("正文", theme="dark")
        self.assertIn('theme: "dark"', rendered.typst)
        self.assertNotIn("#show: use-palette", rendered.typst)

    def test_light_theme_injects_the_palette(self):
        rendered = render_typst("正文", theme="light")
        self.assertIn("#show: use-palette", rendered.typst)

    def test_unknown_theme_is_rejected(self):
        with self.assertRaises(StudyNotesError):
            render_typst("正文", theme="neon")

    def test_latex_math_in_the_draft_is_converted_on_compile(self):
        # 底稿契约是「写 Typst 语法」，但顺手写成 LaTeX 很常见。
        # 报错若是 Typst 的 unknown variable，看不出真正原因是「你写了 LaTeX」。
        rendered = render_typst("[定理] 设 $f(z)$ 满足 $\\sum_{k=1}^{m} a_k = 0$ 则成立")
        self.assertIn("sum_(k = 1)^(m)", rendered.typst)
        self.assertNotIn("\\sum", rendered.typst)

    def test_unconvertible_math_is_named_in_the_warnings(self):
        rendered = render_typst("正文 $x \\foo{y}$ 结束")
        self.assertTrue(any("foo" in item for item in rendered.warnings), rendered.warnings)


class TestCompile(unittest.TestCase):
    """Typst → PDF（需要本机装 Typst）。"""

    def test_end_to_end_compile(self):
        if not find_typst():
            self.skipTest("本机没有 typst，跳过编译测试")
        draft = build_draft(NOTE, author="测试").text
        rendered = render_typst(draft)
        with tempfile.TemporaryDirectory() as directory:
            result = compile_project(directory, rendered.typst, make_png=True)
            self.assertTrue(result.ok, result.errors)
            self.assertTrue(os.path.exists(result.pdf_path))
            self.assertTrue(result.png_paths)
            self.assertTrue(os.path.exists(os.path.join(directory, "prelude.typ")))

    def test_missing_typst_reports_how_to_fix_it(self):
        if find_typst():
            self.skipTest("本机装了 typst，这条只验证错误文案")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(StudyNotesError) as ctx:
                compile_project(directory, "// empty")
            self.assertIn("typst", str(ctx.exception))


class TestMcpTool(unittest.TestCase):
    """zju_build_study_notes 的工具层行为。"""

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

    def _write_note(self):
        path = os.path.join(self.workspace, "知识总结-2026-11-02-复变函数-留数.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(NOTE)
        return path

    def test_draft_mode_writes_a_scaffold(self):
        note = self._write_note()
        report = mcp_server._dispatch_tool(
            "zju_build_study_notes",
            {"mode": "draft", "note_path": note, "author": "测试"},
        )
        self.assertIn("已生成填空底稿", report)
        draft = os.path.join(self.workspace, "知识总结-2026-11-02-复变函数-留数-填空底稿.md")
        self.assertTrue(os.path.exists(draft))
        with open(draft, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("[直觉]", content)

    def test_draft_mode_requires_the_note_path(self):
        report = mcp_server._dispatch_tool("zju_build_study_notes", {"mode": "draft"})
        self.assertIn("note_path", report)

    def test_compile_mode_requires_the_draft_path(self):
        report = mcp_server._dispatch_tool("zju_build_study_notes", {"mode": "compile"})
        self.assertIn("draft_path", report)

    def test_unknown_mode_is_rejected(self):
        report = mcp_server._dispatch_tool("zju_build_study_notes", {"mode": "publish"})
        self.assertIn("draft", report)

    def test_compile_mode_reports_missing_typst_clearly(self):
        note = self._write_note()
        draft_report = mcp_server._dispatch_tool(
            "zju_build_study_notes", {"mode": "draft", "note_path": note}
        )
        self.assertIn("已生成填空底稿", draft_report)
        draft = os.path.join(self.workspace, "知识总结-2026-11-02-复变函数-留数-填空底稿.md")
        report = mcp_server._dispatch_tool(
            "zju_build_study_notes", {"mode": "compile", "draft_path": draft}
        )
        if find_typst():
            self.assertIn("填空笔记编译结果", report)
            self.assertIn("PDF:", report)
        else:
            self.assertIn("typst", report)

    def test_tool_is_advertised(self):
        names = [tool["name"] for tool in mcp_server.TOOLS]
        self.assertIn("zju_build_study_notes", names)

    def test_instructions_mention_the_tool(self):
        self.assertIn("zju_build_study_notes", mcp_server.server_instructions())


class TestLicenseAndAttribution(unittest.TestCase):
    """许可与归属随包分发（这是公开发布的底线）。"""

    def test_skill_ships_its_own_license_and_notices(self):
        base = os.path.join(ROOT, "skills", "scholia-notes")
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "SKILL.md"):
            self.assertTrue(os.path.exists(os.path.join(base, name)), name)

    def test_license_is_mit(self):
        with open(os.path.join(ROOT, "skills", "scholia-notes", "LICENSE"), encoding="utf-8") as handle:
            self.assertIn("MIT License", handle.read())

    def test_notices_name_every_upstream_dependency(self):
        path = os.path.join(ROOT, "skills", "scholia-notes", "THIRD_PARTY_NOTICES.md")
        with open(path, encoding="utf-8") as handle:
            notices = handle.read()
        for token in ("@preview/scholia", "@preview/frame-it", "@preview/marginalia", "MIT", "UNLICENSE"):
            self.assertIn(token, notices)

    def test_skill_declares_it_is_not_the_upstream_project(self):
        path = os.path.join(ROOT, "skills", "scholia-notes", "SKILL.md")
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("非官方", content)
        self.assertIn("未获其背书", content)

    def test_prelude_copy_matches_the_source_of_truth(self):
        source = os.path.join(ROOT, "zju_lecture", "prelude.typ")
        copy = os.path.join(ROOT, "skills", "scholia-notes", "references", "prelude.typ")
        with open(source, "rb") as handle:
            expected = handle.read()
        with open(copy, "rb") as handle:
            actual = handle.read()
        self.assertEqual(expected, actual, "先跑 python tools/sync_skill_assets.py")

    def test_prelude_is_packaged(self):
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as handle:
            self.assertIn("prelude.typ", handle.read())
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertIn("zju_lecture/prelude.typ", manifest["files"])
        self.assertIn("skills/scholia-notes", manifest["files"])

    def test_skill_manifest_lists_every_shipped_file(self):
        manifest_path = os.path.join(ROOT, "skills", "scholia-notes.manifest.json")
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["name"], "scholia-notes")
        paths = {item["path"] for item in manifest["files"]}
        for expected in ("SKILL.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "README.md"):
            self.assertIn(expected, paths)


class TestFormatSpec(unittest.TestCase):
    """格式规范（references/format-spec.md）：正文优先，框框克制。"""

    SPEC = os.path.join(ROOT, "skills", "scholia-notes", "references", "format-spec.md")

    def test_spec_file_exists(self):
        self.assertTrue(os.path.exists(self.SPEC))

    def test_spec_is_referenced_from_the_skill(self):
        with open(os.path.join(ROOT, "skills", "scholia-notes", "SKILL.md"), encoding="utf-8") as handle:
            self.assertIn("format-spec.md", handle.read())
        with open(
            os.path.join(ROOT, "skills", "scholia-notes", "references", "mapping.md"),
            encoding="utf-8",
        ) as handle:
            self.assertIn("format-spec.md", handle.read())

    def test_spec_states_the_body_first_rule(self):
        with open(self.SPEC, encoding="utf-8") as handle:
            spec = handle.read()
        self.assertIn("正文是主角", spec)
        self.assertIn("框框是例外", spec)
        # 语义对应表必须覆盖 md 构造 → PDF 装置
        for token in ("普通段落", "[直觉]", "[定义]", "[定理]", "[练习]", "[边注]", "____"):
            self.assertIn(token, spec)

    def test_scaffold_does_not_insert_boxes(self):
        # 骨架只该插「直觉/练习/边注」。定义、定理、证明是内容判断 ——
        # 自动插框等于替使用者决定「什么该被回指」。
        draft = build_draft(NOTE, author="测试")
        marker_lines = [
            line.strip()
            for line in draft.text.splitlines()
            if line.strip().startswith("[")
        ]
        for marker in ("[定义]", "[定理]", "[证明]", "[例]", "[引理]"):
            self.assertFalse(
                any(line.startswith(marker) for line in marker_lines),
                f"骨架不该插入 {marker}",
            )
        self.assertTrue(any(line.startswith("[直觉]") for line in marker_lines))
        self.assertTrue(any(line.startswith("[练习]") for line in marker_lines))
        self.assertTrue(any(line.startswith("[边注]") for line in marker_lines))

    def test_paragraphs_are_counted(self):
        rendered = render_typst("第一段。\n\n第二段。\n\n## 标题\n\n第三段。")
        self.assertEqual(rendered.paragraphs, 3)

    def test_box_ratio_is_reported(self):
        rendered = render_typst("## 一节\n\n正文一段。\n\n[定义] a —— b")
        self.assertEqual(rendered.knot_count, 1)
        self.assertEqual(rendered.paragraphs, 1)
        self.assertIn("1 : 1", rendered.ratio_text())

    def test_box_heavy_draft_is_flagged(self):
        rendered = render_typst("## 一节\n\n正文。\n\n[定义] a —— b")
        self.assertTrue(rendered.ratio_is_too_many())
        self.assertTrue(any("方框" in item for item in rendered.warnings), rendered.warnings)

    def test_section_budget_is_two_boxes(self):
        three = "\n".join([
            "## 一节",
            "[定义] a —— b",
            "[定理] c —— d",
            "[例] e —— f",
        ])
        self.assertTrue(any("视觉预算" in item for item in render_typst(three).warnings))
        two = "\n".join([
            "## 一节",
            "[定义] a —— b",
            "[定理] c —— d",
        ])
        self.assertFalse(any("视觉预算" in item for item in render_typst(two).warnings))

    def test_html_comment_is_not_rendered(self):
        rendered = render_typst("<!-- 提示：这里要不要用框？ -->\n\n正文一段。")
        self.assertNotIn("要不要用框", rendered.typst)
        self.assertEqual(rendered.paragraphs, 1)

    def test_devices_are_counted(self):
        rendered = render_typst("## 一节\n\n[直觉] 直觉\n\n[练习] 练习\n\n[边注] 边注")
        self.assertEqual(rendered.devices.get("note"), 1)
        self.assertEqual(rendered.devices.get("yourturn"), 1)
        self.assertEqual(rendered.devices.get("recall"), 1)

    def test_body_typography_is_explicit(self):
        # 段首缩进两格 + 段间距略大于行间距 + 公式间距与 par.spacing 解耦。
        typst = render_typst("正文。").typst
        self.assertIn("#h(2em)", typst)
        self.assertIn("leading: 0.72em", typst)
        self.assertIn("spacing: 0.95em", typst)
        self.assertIn("first-line-indent: 0pt", typst)
        self.assertIn("math.equation.where(block: true)", typst)

    def test_paragraph_spacing_is_slightly_larger_than_leading(self):
        from zju_lecture.study_notes import BODY_LEADING, BODY_SPACING

        def _em(value):
            return float(value.removesuffix("em"))

        self.assertGreater(_em(BODY_SPACING), _em(BODY_LEADING))
        # 「略」大于：差距不该大到让段落看起来像换了一节。
        self.assertLess(_em(BODY_SPACING) - _em(BODY_LEADING), _em(BODY_LEADING))

    def test_display_equation_gets_spaces_so_typst_centers_it(self):
        # Typst 只有在 `$` 之后有空白时才把独占一行的公式当块级公式（居中）。
        # 写成 `$x$` 的话它靠左排，还会把首行缩进吃掉。
        typst = render_typst("$x^2 + y^2 = z^2$").typst
        self.assertIn("$ x^2 + y^2 = z^2 $", typst)

    def test_inline_math_keeps_its_form(self):
        typst = render_typst("设 $x$ 为未知量。").typst
        self.assertIn("$x$", typst)
        self.assertNotIn("$ x $", typst)

    def test_every_body_paragraph_gets_the_indent(self):
        # Typst 的 first-line-indent 只在「前一个兄弟是段落」时才生效，
        # 标题后/块后/图后/公式后的段落一律不缩进 —— 所以用 #h(2em) 显式顶首行。
        draft = "\n\n".join([
            "## 标题",
            "标题后的第一段。",
            "[直觉] 直觉块",
            "块后的第一段。",
            "$x^2$",
            "公式后的第一段。",
            "[定理] 结论 —— 正文",
            "框后的第一段。",
        ])
        typst = render_typst(draft).typst
        body = re.sub(
            r"(?s)^.*?math\.equation\.where\(block: true\)[^\n]*\n", "", typst
        )
        for line in body.splitlines():
            if not line.strip():
                continue
            if line.startswith(("#h(2em)", "=", "#", "$", ">")):
                continue
            self.fail(f"正文段落没有段首缩进: {line!r}")

    def test_fillin_uses_a_grey_line_not_the_body_ink(self):
        # 填空线是「留给读者写」的地方，用灰色；黑色会看起来像印刷内容。
        with open(
            os.path.join(ROOT, "zju_lecture", "prelude.typ"), encoding="utf-8"
        ) as handle:
            prelude = handle.read()
        self.assertIn("fillin:", prelude)
        self.assertIn("active.get().fillin", prelude)
        self.assertNotIn("bottom: 0.6pt + active.get().ink", prelude)

    def test_exercise_block_has_no_short_fillin_lines(self):
        # 练习块里已有书写横线，再来几条 2.2cm 的短下划线只会挤在题面里。
        typst = render_typst("[练习] 自己算一次 ____ ____").typst
        self.assertNotIn("#fillin(", typst)
        self.assertIn("#workspace(n: 3)", typst)

    def test_body_blanks_keep_their_fillin(self):
        # 正文里显式写的挖空不受影响，仍然画成灰色填空线。
        typst = render_typst("[定义] 术语 —— 关键处留空：____").typst
        self.assertIn("#fillin(width: 2.2cm)", typst)

    def test_scaffold_exercise_has_no_blanks(self):
        draft = build_draft(NOTE, author="测试")
        self.assertIn("[练习] （留给读者自己重做的一题）", draft.text)
        self.assertNotIn("____ ____ ____", draft.text)


if __name__ == "__main__":
    unittest.main()
