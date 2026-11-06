#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作区边界（安全审查 P0-2 / 7.3）。

模型可以给任意路径。`zju_extract_courseware`、`zju_check_note` 与
`zju_build_study_notes(mode=patch)` 以前只做扩展名/凭据检查，不限制工作区，
于是提示注入可以把「整理课件」变成「读取或改写任意 Markdown」。

这里守住四条：
* 工作区外的读取被拒绝，错误里不回显文件内容；
* 工作区外的 fix / patch 被拒绝，文件 mtime 不变、不产生备份；
* 工作区内的同名操作照常工作；
* 工作区内的符号链接指向外部时按外部处理（realpath 优先）。
"""

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import mcp_server
from mcp_server import handle_tool_call


NOTE_BAD = "| A | B |\n| :--- | :--- |\n| $x$ | $|y|=1$ |\n"
OUTSIDE_SECRET = "OUTSIDE-COURSEWARE-CONTENT"


class WorkspaceBoundaryTestCase(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="zju-ws-")
        self.outside = tempfile.mkdtemp(prefix="zju-outside-")
        self.backup = tempfile.mkdtemp(prefix="zju-backup-")
        self.env = mock.patch.dict(
            os.environ,
            {
                "ZJU_WORKSPACE": self.workspace,
                "PWD": self.workspace,
                "ZJU_BACKUP_DIR": self.backup,
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        for directory in (self.workspace, self.outside, self.backup):
            shutil.rmtree(directory, ignore_errors=True)

    def _write(self, directory, name, text):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


class TestOutsideWorkspaceRejected(WorkspaceBoundaryTestCase):

    def test_extract_courseware_rejects_outside_markdown(self):
        path = self._write(self.outside, "课件.md", OUTSIDE_SECRET)
        output = handle_tool_call("zju_extract_courseware", {"file_path": path})
        self.assertIn("拒绝访问工作区之外的文件", output)
        self.assertNotIn(OUTSIDE_SECRET, output)

    def test_check_note_rejects_outside_markdown(self):
        path = self._write(self.outside, "讲义.md", OUTSIDE_SECRET)
        output = handle_tool_call("zju_check_note", {"file_path": path})
        self.assertIn("拒绝访问工作区之外的文件", output)
        self.assertNotIn(OUTSIDE_SECRET, output)

    def test_check_note_fix_rejects_outside_and_leaves_file_untouched(self):
        path = self._write(self.outside, "讲义.md", NOTE_BAD)
        before_stat = os.stat(path)
        with open(path, "rb") as handle:
            before_bytes = handle.read()
        time.sleep(0.01)

        output = handle_tool_call("zju_check_note", {"file_path": path, "fix": True})

        self.assertIn("拒绝访问工作区之外的文件", output)
        after_stat = os.stat(path)
        self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before_bytes)
        self.assertEqual(os.listdir(self.backup), [], "拒绝写入时不应产生备份")
        self.assertEqual(
            [name for name in os.listdir(self.outside) if name.endswith(".bak")],
            [],
        )

    def test_patch_rejects_outside_draft(self):
        path = self._write(self.outside, "底稿.md", "# 底稿\n\n原文 A\n")
        output = handle_tool_call(
            "zju_build_study_notes",
            {
                "mode": "patch",
                "draft_path": path,
                "edits": [{"old": "原文 A", "new": "原文 B"}],
            },
        )
        self.assertIn("拒绝访问工作区之外的文件", output)
        with open(path, encoding="utf-8") as handle:
            self.assertIn("原文 A", handle.read())

    def _link_outside(self, name):
        """Return a workspace path that resolves outside (file link or junction)."""
        target = self._write(self.outside, name, OUTSIDE_SECRET)
        link = os.path.join(self.workspace, name)
        try:
            os.symlink(target, link)
            return link, None
        except (OSError, NotImplementedError):
            pass
        # Windows 普通用户建不了符号链接，但目录 junction 不需要提权。
        junction = os.path.join(self.workspace, "linked-outside")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", junction, self.outside],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None, (result.stderr or result.stdout or "无法创建符号链接/junction").strip()
        return os.path.join(junction, name), junction

    def test_symlink_to_outside_is_rejected(self):
        link, cleanup = self._link_outside("外部讲义.md")
        if link is None:
            self.skipTest(f"本机无法创建符号链接: {cleanup}")
        try:
            for tool, args in (
                ("zju_extract_courseware", {"file_path": link}),
                ("zju_check_note", {"file_path": link}),
            ):
                with self.subTest(tool=tool):
                    output = handle_tool_call(tool, args)
                    self.assertIn("拒绝访问工作区之外的文件", output)
                    self.assertNotIn(OUTSIDE_SECRET, output)
        finally:
            if cleanup and os.path.isdir(cleanup):
                os.rmdir(cleanup)  # 只删 junction，不动目标目录


class TestInsideWorkspaceStillWorks(WorkspaceBoundaryTestCase):

    def test_extract_courseware_inside_workspace(self):
        path = self._write(self.workspace, "课件.md", "# 线性代数\n\n矩阵与行列式。\n")
        output = handle_tool_call("zju_extract_courseware", {"file_path": path})
        self.assertIn("课件文件提取成功", output)
        self.assertIn("线性代数", output)
        self.assertNotIn("已读取工作区外文件", output)

    def test_check_note_fix_inside_workspace(self):
        path = self._write(self.workspace, "讲义.md", NOTE_BAD)
        output = handle_tool_call("zju_check_note", {"file_path": path, "fix": True})
        self.assertIn("已自动修复", output)
        with open(path, encoding="utf-8") as handle:
            self.assertIn("\\lvert y\\rvert", handle.read())

    def test_patch_inside_workspace(self):
        path = self._write(self.workspace, "底稿.md", "# 底稿\n\n原文 A\n")
        output = handle_tool_call(
            "zju_build_study_notes",
            {
                "mode": "patch",
                "draft_path": path,
                "edits": [{"old": "原文 A", "new": "原文 B"}],
            },
        )
        self.assertIn("已修改填空底稿", output)
        with open(path, encoding="utf-8") as handle:
            self.assertIn("原文 B", handle.read())

    def test_allow_outside_workspace_is_explicit_and_annotated(self):
        path = self._write(self.outside, "课件.md", OUTSIDE_SECRET)
        output = handle_tool_call(
            "zju_extract_courseware",
            {"file_path": path, "allow_outside_workspace": True},
        )
        self.assertTrue(output.startswith("已读取工作区外文件: "), output[:80])
        self.assertIn(OUTSIDE_SECRET, output)

    def test_allow_outside_workspace_still_refuses_credentials(self):
        path = self._write(self.outside, "client_secret.md", "PRIVATE=1")
        output = handle_tool_call(
            "zju_extract_courseware",
            {"file_path": path, "allow_outside_workspace": True},
        )
        self.assertIn("隐私", output)
        self.assertNotIn("PRIVATE=1", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
