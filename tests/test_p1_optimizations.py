# -*- coding: utf-8 -*-
"""P1 regression tests: image/PDF reports, dedupe label, docs consistency."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import mcp_server
from zju_lecture.handout import HandoutCompileResult
from zju_lecture import slides as slides_module


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="zju-p1-workspace-")
        self.backups = tempfile.mkdtemp(prefix="zju-p1-backups-")
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.addCleanup(shutil.rmtree, self.backups, True)
        self.env = {
            "ZJU_WORKSPACE": self.workspace,
            "PWD": self.workspace,
            "ZJU_BACKUP_DIR": self.backups,
            "ZJU_RENDER_PDF": "0",
        }

    def write(self, name, body):
        path = os.path.join(self.workspace, name)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        return path

    def read(self, name):
        with open(os.path.join(self.workspace, name), encoding="utf-8") as handle:
            return handle.read()


class TestNoteImageReport(WorkspaceCase):
    def test_existing_and_missing_images_are_reported(self):
        self.write("ppt-assets/1/slide-0001.jpg", "not really a jpeg")
        note = self.write(
            "note.md",
            "![ok](ppt-assets/1/slide-0001.jpg)\n"
            "![bad](ppt-assets/1/missing.jpg)\n",
        )
        with mock.patch.dict(os.environ, self.env):
            report = mcp_server._note_image_report(
                self.read("note.md"), note
            )
        self.assertIn("图片引用: 2 张", report)
        self.assertIn("缺失/不可用 1 张", report)
        self.assertIn("missing.jpg", report)
        self.assertNotIn("slide-0001.jpg", report.split("缺失/不可用", 1)[1])

    def test_external_images_are_counted_but_not_checked(self):
        note = self.write(
            "note.md",
            "![remote](https://example.com/x.jpg)\n",
        )
        with mock.patch.dict(os.environ, self.env):
            report = mcp_server._note_image_report(
                self.read("note.md"), note
            )
        self.assertIn("图片引用: 1 张", report)
        self.assertIn("外链 1 张（PDF 不嵌入）", report)

    def test_no_images_has_no_report(self):
        note = self.write("note.md", "# 讲义\n")
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(
                mcp_server._note_image_report(
                    self.read("note.md"), note
                ),
                "",
            )

    def test_images_inside_code_fences_are_ignored(self):
        note = self.write(
            "note.md",
            "```markdown\n![example](ppt-assets/missing.jpg)\n```\n",
        )
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(
                mcp_server._note_image_report(self.read("note.md"), note),
                "",
            )


class TestWriteNoteImageReport(WorkspaceCase):
    def test_write_note_reports_missing_image(self):
        with mock.patch.dict(os.environ, self.env):
            output = mcp_server.handle_tool_call(
                "zju_write_note",
                {
                    "sub_id": "1",
                    "name": "知识总结-2026-11-12-测试",
                    "content": "# 讲义\n\n![bad](ppt-assets/missing.jpg)\n",
                },
            )
        self.assertIn("图片引用: 1 张", output)
        self.assertIn("缺失/不可用 1 张", output)


class TestCheckNoteImageReport(WorkspaceCase):
    def test_check_note_reports_missing_image(self):
        self.write(
            "note.md",
            "# 讲义\n\n![bad](ppt-assets/missing.jpg)\n",
        )
        with mock.patch.dict(os.environ, self.env):
            output = mcp_server.handle_tool_call(
                "zju_check_note", {"file_path": "note.md"}
            )
        self.assertIn("图片引用: 1 张", output)
        self.assertIn("缺失/不可用 1 张", output)


class TestPdfWarnings(WorkspaceCase):
    def test_successful_pdf_surfaces_warnings(self):
        note = self.write("note.md", "# 讲义\n")
        result = HandoutCompileResult(
            ok=True,
            pdf_path=os.path.join(self.workspace, "note.pdf"),
            pages=2,
            warnings=["找不到图片（ppt-assets/missing.jpg）"],
        )
        with mock.patch.dict(os.environ, self.env), mock.patch(
            "zju_lecture.handout.compile_handout_file", return_value=result
        ):
            lines = mcp_server._render_note_pdf(note, "# 讲义\n")
        self.assertTrue(any(line.startswith("PDF: ") for line in lines))
        self.assertIn("PDF 提示:", lines)
        self.assertTrue(any("找不到图片" in line for line in lines))

    def test_failed_pdf_also_surfaces_warnings(self):
        note = self.write("note.md", "# 讲义\n")
        result = HandoutCompileResult(
            ok=False,
            errors=["typst error: something"],
            warnings=["找不到图片（ppt-assets/missing.jpg）"],
        )
        with mock.patch.dict(os.environ, self.env), mock.patch(
            "zju_lecture.handout.compile_handout_file", return_value=result
        ):
            lines = mcp_server._render_note_pdf(note, "# 讲义\n")
        self.assertTrue(any(line.startswith("PDF 跳过: ") for line in lines))
        self.assertIn("PDF 提示:", lines)
        self.assertTrue(any("找不到图片" in line for line in lines))


class TestDedupeLabelAndIndex(WorkspaceCase):
    def test_label_is_explicit_and_index_uses_kept_pages(self):
        slides = [
            {
                "page": 1,
                "image_url": "https://media.cmc.zju.edu.cn/1.jpg",
                "local_path": "/tmp/ppt/slide-0001.jpg",
                "workspace_rel": "ppt-assets/1/slide-0001.jpg",
            },
            {
                "page": 2,
                "image_url": "https://media.cmc.zju.edu.cn/2.jpg",
                "local_path": "/tmp/ppt/slide-0002.jpg",
                "workspace_rel": "ppt-assets/1/slide-0002.jpg",
            },
            {
                "page": 3,
                "image_url": "https://media.cmc.zju.edu.cn/3.jpg",
                "local_path": "/tmp/ppt/slide-0003.jpg",
                "workspace_rel": "ppt-assets/1/slide-0003.jpg",
            },
        ]
        kept = slides[:2]
        summary = {
            "downloaded": 3,
            "failed": 0,
            "skipped": 0,
            "duplicates": 1,
            "images_dir": "/tmp/ppt",
            "pages": kept,
            "total_bytes": 10,
            "note_example": "![第 1 页](ppt-assets/1/slide-0001.jpg)",
        }
        with mock.patch.dict(
            os.environ, {"ZJU_EMBED_SLIDES": "0", "ZJU_SLIDES_SOURCE": "0"}
        ), mock.patch.object(
            mcp_server, "_resolve_cookie", return_value=("S=1", None, "cache", None)
        ), mock.patch.object(
            mcp_server, "fetch_slides", return_value=slides
        ), mock.patch.object(
            mcp_server, "artifact_dir", return_value=("/tmp/ppt", None)
        ), mock.patch.object(
            slides_module, "download_slides", return_value=summary
        ), mock.patch.object(
            slides_module, "build_slides_pdf", return_value="/tmp/ppt/PPT-1.pdf"
        ):
            output = mcp_server.handle_tool_call(
                "zju_fetch_slides",
                {
                    "url_or_sub_id": (
                        "https://classroom.zju.edu.cn/livingroom?course_id=1&sub_id=1"
                    ),
                    "download": True,
                    "confirm": True,
                },
            )
        self.assertIn("连续字节完全重复折叠 1 张", output)
        self.assertIn("共 2 页", output)
        self.assertNotIn("共 3 页", output)


class TestP1Docs(unittest.TestCase):
    def test_slide_asset_path_has_no_images_subdir(self):
        for rel in ("skills/zju-lecture-summarizer/SLIDES.md", "lib/index.js"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
                text = handle.read()
            self.assertNotIn("/images/slide", text, rel)

    def test_login_guidance_uses_login_window(self):
        path = os.path.join(ROOT, "skills/zju-lecture-summarizer/SLIDES.md")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("zju_login", text)
        self.assertNotIn("完全退出 Edge", text)
        self.assertNotIn("引导用户设置 `ZJU_COOKIE_FILE`", text)

    def test_image_report_is_documented(self):
        path = os.path.join(ROOT, "skills/zju-lecture-summarizer/SLIDES.md")
        with open(path, encoding="utf-8") as handle:
            self.assertIn("图片引用", handle.read())


if __name__ == "__main__":
    unittest.main()
