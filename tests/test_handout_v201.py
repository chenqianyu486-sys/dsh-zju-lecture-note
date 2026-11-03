# -*- coding: utf-8 -*-
"""v2.0.1 讲义 PDF 自动排版 + 功能门控回归。

守三件事：

1. **讲义 PDF 是自动增益**：写 Markdown + 校验 + 排版一次完成；Typst 不可用
   或排版失败时，Markdown 仍然写入成功，只跳过 PDF。
2. **排版内容不丢结构**：标题、段落、列表、表格、公式、代码、引用、图片
   都要进 PDF；不认识的结构降级并在 warnings 里点名。
3. **可选模块真的解耦**：开关关闭时工具不出现在 tools/list，直接调用会得到
   可行动的错误；MCP 宿主未设置环境变量时保持旧行为。
"""

import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import mcp_server  # noqa: E402
from zju_lecture.handout import (  # noqa: E402
    compile_handout,
    render_handout,
)
from zju_lecture.study_notes import find_typst  # noqa: E402


NOTE = r"""# 复变函数 第 3 讲：留数定理

> 上课日期：2026-10-28

## 留数的定义

设 $f(z)$ 在孤立奇点 $z_0$ 处的 Laurent 展开为

$$
\sum_{n=-\infty}^{\infty} a_n (z-z_0)^n
$$

则留数定义为 $a_{-1}$，**不是** `i`。

- 第一条：$\frac{1}{2\pi i}$
  - 子项
- 第二条

| 概念 | 记号 | 说明 |
| --- | --- | --- |
| 留数 | $a_{-1}$ | Laurent 展开系数 |

> [!IMPORTANT]
> 这是重点提示。

```python
def f(x):
    return x + 1
```

---

### 留数定理

$$ \oint_C f(z) \, dz = 2\pi i \sum_k \operatorname{Res}(f, z_k) $$

## 例题

看完 [课程页面](https://classroom.zju.edu.cn/) 后重做一遍。
"""


def write_note(directory, stem="知识总结-2026-10-28-复变函数-留数定理", text=NOTE):
    path = os.path.join(directory, stem + ".md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


class TestRenderHandout(unittest.TestCase):
    def test_cover_and_heading_mapping(self):
        rendered = render_handout(NOTE)
        self.assertEqual(rendered.title, "复变函数 第 3 讲")
        self.assertEqual(rendered.subtitle, "留数定理")
        self.assertIn('#cover("复变函数 第 3 讲", subtitle: "留数定理"', rendered.typst)
        self.assertIn("= 留数的定义", rendered.typst)
        self.assertIn("== 留数定理", rendered.typst)
        self.assertNotIn("# 复变函数 第 3 讲", rendered.typst)

    def test_blocks_are_rendered(self):
        rendered = render_handout(NOTE)
        self.assertIn("#table(", rendered.typst)
        self.assertIn("table.header(", rendered.typst)
        self.assertIn("$ sum_(n = -∞)^(∞) a_n (z-z_0)^n $", rendered.typst)
        self.assertIn("#raw(", rendered.typst)
        self.assertIn('lang: "python"', rendered.typst)
        self.assertIn("*重点*", rendered.typst)
        self.assertIn("- 第一条", rendered.typst)
        self.assertIn("#link(\"https://classroom.zju.edu.cn/\")", rendered.typst)
        self.assertIn("#h(2em)", rendered.typst)
        self.assertEqual(rendered.blocks.get("table"), 1)
        self.assertEqual(rendered.blocks.get("code"), 1)

    def test_comments_details_and_missing_image(self):
        text = (
            "# 标题\n\n"
            "<!-- 不渲染的备注 -->\n\n"
            "<details>\n<summary>补充</summary>\n\n正文。\n</details>\n\n"
            "![示意图](ppt-assets/missing.png)\n"
        )
        rendered = render_handout(text)
        self.assertNotIn("不渲染的备注", rendered.typst)
        self.assertNotIn("<details>", rendered.typst)
        self.assertIn("*补充*", rendered.typst)
        self.assertTrue(any("找不到图片" in item for item in rendered.warnings))

    def test_hard_break_is_a_typst_break_not_literal_text(self):
        rendered = render_handout("# 标题\n\n第一行  \n第二行\n")
        self.assertIn("#linebreak()", rendered.typst)
        self.assertNotIn("\\#linebreak()", rendered.typst)

    def test_three_sections_add_a_toc(self):
        text = "# 标题\n\n## 一\n\n正文\n\n## 二\n\n正文\n\n## 三\n\n正文\n"
        rendered = render_handout(text)
        self.assertGreaterEqual(rendered.sections, 3)
        self.assertIn("#outline(", rendered.typst)

    def test_table_without_separator_falls_back_to_paragraph(self):
        text = "# 标题\n\n| 这不是 | 表格 |\n"
        rendered = render_handout(text)
        self.assertNotIn("#table(", rendered.typst)
        self.assertIn("| 这不是 | 表格 |", rendered.typst)


@unittest.skipUnless(find_typst(), "本机没有 Typst，跳过真实 PDF 编译")
class TestCompileHandout(unittest.TestCase):
    def test_compile_produces_a_pdf_and_no_page_png(self):
        directory = tempfile.mkdtemp()
        note = write_note(directory)
        rendered = render_handout(NOTE, workspace_root=directory, note_path=note)
        pdf = os.path.join(directory, "out.pdf")
        result = compile_handout(rendered.typst, pdf, workspace_root=directory)
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(os.path.isfile(pdf))
        self.assertGreater(result.pages, 0)
        with open(pdf, "rb") as handle:
            self.assertTrue(handle.read(4) == b"%PDF")
        # 讲义 PDF 不需要逐页 PNG；那会把编译时间翻倍并留下几十个文件。
        build = os.path.join(directory, ".zju-lecture", "handout", "out")
        self.assertFalse(
            any(name.endswith(".png") for name in os.listdir(build)),
            os.listdir(build),
        )

    def test_missing_typst_is_reported_not_raised(self):
        with mock.patch("zju_lecture.handout.find_typst", return_value=None):
            result = compile_handout("#import \"prelude.typ\": *\n", "/tmp/x.pdf", "/tmp")
        self.assertFalse(result.ok)
        self.assertIn("找不到 typst", result.errors[0])


class TestTranscriptProcessStaysLean(unittest.TestCase):
    def test_importing_the_server_does_not_load_the_pdf_module(self):
        import subprocess

        code = (
            "import sys, mcp_server; "
            "print('zju_lecture.handout' in sys.modules, 'zju_lecture.study_notes' in sys.modules)"
        )
        env = dict(os.environ)
        env.update({"ZJU_ENABLE_SLIDES": "0", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # study_notes is imported for the tool constants; handout is lazy.
        self.assertEqual(result.stdout.strip(), "False True", result.stdout)


class TestHandoutTemplateIsSelfContained(unittest.TestCase):
    def test_template_has_no_universe_package_import(self):
        path = os.path.join(ROOT, "zju_lecture", "handout_prelude.typ")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        # 注释里可以解释「为什么不用 @preview/scholia」，但不能真的 import。
        self.assertNotIn('#import "@preview/', text)
        self.assertIn("#let cover(", text)

    def test_template_and_module_are_packaged(self):
        import json

        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertIn("zju_lecture/handout_prelude.typ", manifest["files"])
        self.assertIn("zju_lecture/*.py", manifest["files"])
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as handle:
            pyproject = handle.read()
        self.assertIn("handout_prelude.typ", pyproject)


class TestAutoPdfOnWrite(unittest.TestCase):
    def test_write_note_generates_a_pdf_by_default(self):
        if not find_typst():
            self.skipTest("本机没有 Typst")
        directory = tempfile.mkdtemp()
        env = {
            "ZJU_WORKSPACE": directory,
            "ZJU_ENABLE_SLIDES": "0",
            "ZJU_ENABLE_STUDY_NOTES": "0",
            "ZJU_ENABLE_LOGIN_TOOLS": "0",
            "ZJU_RENDER_PDF": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            output = mcp_server.handle_tool_call(
                "zju_write_note",
                {
                    "sub_id": "123456",
                    "name": "知识总结-2026-10-28-复变函数-留数定理",
                    "content": NOTE,
                },
            )
        self.assertIn("=== 已写入讲义 ===", output)
        self.assertIn("PDF:", output)
        pdf = os.path.join(directory, "知识总结-2026-10-28-复变函数-留数定理.pdf")
        self.assertTrue(os.path.isfile(pdf), output)
        self.assertIn("结论: 通过", output)

    def test_render_pdf_off_writes_only_markdown(self):
        directory = tempfile.mkdtemp()
        env = {
            "ZJU_WORKSPACE": directory,
            "ZJU_ENABLE_SLIDES": "0",
            "ZJU_ENABLE_STUDY_NOTES": "0",
            "ZJU_ENABLE_LOGIN_TOOLS": "0",
            "ZJU_RENDER_PDF": "0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            output = mcp_server.handle_tool_call(
                "zju_write_note",
                {
                    "sub_id": "123456",
                    "name": "知识总结-2026-10-28-复变函数",
                    "content": NOTE,
                },
            )
        self.assertNotIn("PDF:", output)
        self.assertFalse(
            os.path.exists(os.path.join(directory, "知识总结-2026-10-28-复变函数.pdf"))
        )

    def test_explicit_pdf_false_overrides_the_setting(self):
        directory = tempfile.mkdtemp()
        env = {
            "ZJU_WORKSPACE": directory,
            "ZJU_ENABLE_SLIDES": "0",
            "ZJU_ENABLE_STUDY_NOTES": "0",
            "ZJU_ENABLE_LOGIN_TOOLS": "0",
            "ZJU_RENDER_PDF": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            output = mcp_server.handle_tool_call(
                "zju_write_note",
                {
                    "sub_id": "123456",
                    "name": "知识总结-2026-10-28-复变函数",
                    "content": NOTE,
                    "pdf": False,
                },
            )
        self.assertNotIn("PDF:", output)

    def test_missing_typst_does_not_fail_the_write(self):
        directory = tempfile.mkdtemp()
        env = {
            "ZJU_WORKSPACE": directory,
            "ZJU_ENABLE_SLIDES": "0",
            "ZJU_ENABLE_STUDY_NOTES": "0",
            "ZJU_ENABLE_LOGIN_TOOLS": "0",
            "ZJU_RENDER_PDF": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False), mock.patch(
            "zju_lecture.handout.find_typst", return_value=None
        ):
            output = mcp_server.handle_tool_call(
                "zju_write_note",
                {
                    "sub_id": "123456",
                    "name": "知识总结-2026-10-28-复变函数",
                    "content": NOTE,
                },
            )
        self.assertIn("PDF 跳过", output)
        self.assertIn("Markdown", output)
        self.assertTrue(
            os.path.isfile(os.path.join(directory, "知识总结-2026-10-28-复变函数.md"))
        )

    def test_check_note_pdf_true_rerenders(self):
        if not find_typst():
            self.skipTest("本机没有 Typst")
        directory = tempfile.mkdtemp()
        note = write_note(directory)
        env = {
            "ZJU_WORKSPACE": directory,
            "ZJU_ENABLE_SLIDES": "0",
            "ZJU_ENABLE_STUDY_NOTES": "0",
            "ZJU_ENABLE_LOGIN_TOOLS": "0",
            "ZJU_RENDER_PDF": "0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            output = mcp_server.handle_tool_call(
                "zju_check_note", {"file_path": note, "pdf": True}
            )
        self.assertIn("PDF:", output)
        self.assertTrue(os.path.isfile(os.path.splitext(note)[0] + ".pdf"))


class TestFeatureGates(unittest.TestCase):
    def names(self, **env):
        base = {
            "ZJU_ENABLE_SLIDES": "0",
            "ZJU_ENABLE_STUDY_NOTES": "0",
            "ZJU_ENABLE_LOGIN_TOOLS": "0",
            "ZJU_RENDER_PDF": "0",
        }
        base.update(env)
        with mock.patch.dict(os.environ, base, clear=False):
            return [tool["name"] for tool in mcp_server.available_tools()]

    def test_default_has_five_tools(self):
        names = self.names()
        self.assertEqual(len(names), 5)
        self.assertEqual(
            names,
            [
                "zju_parse_url",
                "zju_fetch_transcript",
                "zju_extract_courseware",
                "zju_check_note",
                "zju_write_note",
            ],
        )

    def test_each_optional_module_adds_only_its_own_tools(self):
        study = self.names(ZJU_ENABLE_STUDY_NOTES="1")
        self.assertIn("zju_build_study_notes", study)
        self.assertNotIn("zju_fetch_slides", study)

        login = self.names(ZJU_ENABLE_LOGIN_TOOLS="1")
        self.assertIn("zju_get_video_url", login)
        self.assertIn("zju_read_browser_cookie", login)
        self.assertNotIn("zju_build_study_notes", login)

        slides = self.names(ZJU_ENABLE_SLIDES="1")
        self.assertIn("zju_fetch_slides", slides)
        self.assertNotIn("zju_get_video_url", slides)

        everything = self.names(
            ZJU_ENABLE_STUDY_NOTES="1",
            ZJU_ENABLE_LOGIN_TOOLS="1",
            ZJU_ENABLE_SLIDES="1",
        )
        self.assertEqual(len(everything), 9)

    def test_disabled_tool_call_is_an_actionable_error(self):
        env = {
            "ZJU_ENABLE_STUDY_NOTES": "0",
            "ZJU_ENABLE_LOGIN_TOOLS": "0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(mcp_server.StudyNotesDisabledError) as study:
                mcp_server.handle_tool_call("zju_build_study_notes", {"mode": "draft"})
            with self.assertRaises(mcp_server.LoginToolsDisabledError) as login:
                mcp_server.handle_tool_call("zju_read_browser_cookie", {})
        self.assertIn("enableStudyNotes", str(study.exception))
        self.assertIn("ZJU_ENABLE_STUDY_NOTES=1", str(study.exception))
        self.assertIn("enableLoginTools", str(login.exception))

    def test_mcp_default_keeps_the_old_modules_enabled(self):
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in (
                "ZJU_ENABLE_SLIDES",
                "ZJU_ENABLE_STUDY_NOTES",
                "ZJU_ENABLE_LOGIN_TOOLS",
                "ZJU_RENDER_PDF",
            )
        }
        with mock.patch.dict(os.environ, env, clear=True):
            names = [tool["name"] for tool in mcp_server.available_tools()]
            self.assertEqual(len(names), 9)
            self.assertFalse(mcp_server.render_pdf_enabled())


class TestServerInstructions(unittest.TestCase):
    def test_instructions_name_the_pdf_and_gates(self):
        env = {
            "ZJU_ENABLE_SLIDES": "0",
            "ZJU_ENABLE_STUDY_NOTES": "0",
            "ZJU_ENABLE_LOGIN_TOOLS": "0",
            "ZJU_RENDER_PDF": "0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            text = mcp_server.server_instructions()
        self.assertIn("PDF 自动排版已关闭", text)
        self.assertIn("填空笔记已关闭", text)
        self.assertIn("登录辅助工具已关闭", text)
        self.assertIn("投影抓取已关闭", text)

        with mock.patch.dict(
            os.environ,
            {
                "ZJU_ENABLE_SLIDES": "1",
                "ZJU_ENABLE_STUDY_NOTES": "1",
                "ZJU_ENABLE_LOGIN_TOOLS": "1",
                "ZJU_RENDER_PDF": "1",
            },
            clear=False,
        ):
            text = mcp_server.server_instructions()
        self.assertIn("ZJU_RENDER_PDF=0", text)
        self.assertIn("zju_build_study_notes", text)
        self.assertIn("视频直链", text)
        self.assertIn("投影截图", text)


if __name__ == "__main__":
    unittest.main()
