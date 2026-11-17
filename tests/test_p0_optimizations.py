# -*- coding: utf-8 -*-
"""P0 regression tests: long-note content_file and compact slide index."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

import mcp_server
from zju_lecture.formatter import format_slides_as_markdown


class TestWriteNoteContentFile(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="zju-p0-workspace-")
        self.backups = tempfile.mkdtemp(prefix="zju-p0-backups-")
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.addCleanup(shutil.rmtree, self.backups, True)
        self.env = {
            "ZJU_WORKSPACE": self.workspace,
            "PWD": self.workspace,
            "ZJU_BACKUP_DIR": self.backups,
            "ZJU_RENDER_PDF": "0",
        }

    def _call(self, **arguments):
        with mock.patch.dict(os.environ, self.env):
            return mcp_server.handle_tool_call("zju_write_note", arguments)

    def _draft(self, name="draft.md", body="# 讲义\n\n正文 $x=1$。\n"):
        path = os.path.join(self.workspace, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        return path

    def test_content_file_is_written_without_inline_content(self):
        self._draft()
        output = self._call(
            sub_id="1",
            content_file="draft.md",
            name="知识总结-2026-11-12-测试",
        )
        self.assertIn("已写入讲义", output)
        target = os.path.join(self.workspace, "知识总结-2026-11-12-测试.md")
        self.assertTrue(os.path.isfile(target))
        with open(target, encoding="utf-8") as handle:
            self.assertIn("正文", handle.read())
        self.assertNotIn("PDF:", output)

    def test_content_and_content_file_are_mutually_exclusive(self):
        self._draft()
        with self.assertRaises(ValueError):
            self._call(sub_id="1", content="# 正文", content_file="draft.md")

    def test_missing_content_and_content_file_raises(self):
        with self.assertRaises(ValueError):
            self._call(sub_id="1")

    def test_content_file_outside_workspace_is_refused(self):
        outside = tempfile.mkdtemp(prefix="zju-p0-outside-")
        self.addCleanup(shutil.rmtree, outside, True)
        outside_file = os.path.join(outside, "note.md")
        with open(outside_file, "w", encoding="utf-8") as handle:
            handle.write("# 外部\n")
        output = self._call(sub_id="1", content_file=outside_file)
        self.assertIn("工作区之外", output)

    def test_missing_draft_is_reported(self):
        output = self._call(sub_id="1", content_file="missing.md")
        self.assertIn("找不到讲义草稿", output)

    def test_same_named_draft_can_be_finalized_in_place(self):
        draft = self._draft(
            "知识总结-2026-11-12-测试.md",
            "# 讲义\n\n$$\n\\frac12\n$$\n",
        )
        output = self._call(sub_id="1", content_file=draft)
        self.assertIn("已写入讲义", output)
        self.assertNotIn("同名讲义已存在", output)
        self.assertTrue(os.path.isfile(draft))
        self.assertEqual(len(os.listdir(self.backups)), 1)


class TestCompactSlideIndex(unittest.TestCase):
    def test_compact_index_is_much_smaller_than_per_page_paths(self):
        slides = [
            {
                "page": index,
                "time": index * 30,
                "local_path": "/tmp/workspace/ppt-assets/1/slide-%04d.jpg" % index,
                "workspace_rel": "ppt-assets/1/slide-%04d.jpg" % index,
            }
            for index in range(1, 151)
        ]
        compact = format_slides_as_markdown(slides, compact=True)
        detailed = format_slides_as_markdown(slides)
        self.assertLess(len(compact), len(detailed) / 3)
        self.assertIn("页时间轴", compact)
        self.assertIn("建议抽查", compact)
        self.assertNotIn("工作区相对路径:", compact)


if __name__ == "__main__":
    unittest.main()

class TestP0Documentation(unittest.TestCase):
    @staticmethod
    def _read(*parts):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, *parts), encoding="utf-8") as handle:
            return handle.read()

    def test_slide_budget_is_in_the_prompt_and_skill(self):
        prompt = self._read("lib", "index.js")
        slides = self._read("skills", "zju-lecture-summarizer", "SLIDES.md")
        self.assertIn("15–25", prompt)
        self.assertIn("不要逐页通读", slides)

    def test_skill_documents_content_file(self):
        skill = self._read("skills", "zju-lecture-summarizer", "SKILL.md")
        self.assertIn("content_file", skill)
        self.assertIn("同一个**程序", skill)

