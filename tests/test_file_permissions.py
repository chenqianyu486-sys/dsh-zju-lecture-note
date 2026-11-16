#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时文件与备份权限（安全审查 P1-3 / 7.6）。

* 登录态临时文件曾用固定的 ``session.bin.tmp``（O_TRUNC，可被预置链接劫持）；
* 截图 / PDF 的 ``.part`` 也是固定路径；
* 备份目录继承 umask、文件名可预测、copyfile 会跟随符号链接。

现在统一 mkstemp + os.replace；备份目录 0700、备份文件 0600、文件名带
随机后缀；写入前用 lstat 拒绝符号链接。权限位只在 POSIX 上有意义。
"""

import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

from zju_lecture import browser_login, cookies, handout, note_lint

COOKIE = "sid=abc123; _token=" + "T" * 40


class TestRandomBackupNames(unittest.TestCase):
    """跨平台可验证的部分：文件名不再可预测。"""

    def test_unique_backup_path_has_random_suffix(self):
        directory = tempfile.mkdtemp(prefix="zju-backup-")
        try:
            first = note_lint._unique_backup_path(directory, "/tmp/讲义.md")
            second = note_lint._unique_backup_path(directory, "/tmp/讲义.md")
            self.assertNotEqual(first, second)
            self.assertTrue(first.endswith(".bak"))
            self.assertRegex(os.path.basename(first), r"^讲义\.\d{8}-\d{6}\.[0-9a-f]{8}\.bak$")
        finally:
            shutil.rmtree(directory, ignore_errors=True)


class TestLoginSessionStorage(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="zju-login-")
        self.env = mock.patch.dict(
            os.environ,
            {
                "ZJU_LOGIN_DIR": self.directory,
                # A test must never write to the developer's real keyring.
                "ZJU_LOGIN_STORAGE": "memory" if sys.platform != "win32" else "os",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.directory, ignore_errors=True)

    @unittest.skipUnless(sys.platform == "win32", "只有 Windows 后端写文件")
    def test_windows_session_file_is_atomic_and_private(self):
        browser_login.save_session(COOKIE)
        names = os.listdir(self.directory)
        self.assertTrue(any(name.startswith("session") for name in names), names)
        self.assertEqual([name for name in names if name.endswith(".tmp")], [], names)
        self.assertTrue(os.path.isfile(browser_login.session_file()))

    @unittest.skipIf(sys.platform == "win32", "POSIX 后端不写任何凭据文件")
    def test_posix_writes_no_credential_file(self):
        browser_login.save_session(COOKIE)
        self.assertFalse(os.path.exists(browser_login.session_file()))
        self.assertEqual(
            [name for name in os.listdir(self.directory) if name.endswith(".tmp")], []
        )


class TestNotePdfCopy(unittest.TestCase):
    """``handout._atomic_copy`` must not follow a planted ``.tmp`` symlink."""

    def test_planted_symlink_at_the_old_fixed_tmp_name_is_ignored(self):
        directory = tempfile.mkdtemp(prefix="zju-pdf-copy-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        source = os.path.join(directory, "out.pdf")
        with open(source, "wb") as handle:
            handle.write(b"%PDF-1.4 new")
        target = os.path.join(directory, "讲义.pdf")
        with open(target, "wb") as handle:
            handle.write(b"%PDF-1.4 old")
        outside = os.path.join(directory, "outside.txt")
        with open(outside, "wb") as handle:
            handle.write(b"untouched")
        try:
            os.symlink(outside, target + ".tmp")
        except (OSError, NotImplementedError, AttributeError):
            self.skipTest("当前环境无法创建符号链接")

        handout._atomic_copy(source, target)

        with open(outside, "rb") as handle:
            self.assertEqual(handle.read(), b"untouched")
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), b"%PDF-1.4 new")
        # The planted link belongs to the caller. The copy must ignore it,
        # not remove it; only temporary files created by the copy are cleaned.
        self.assertTrue(os.path.islink(target + ".tmp"))
        self.assertTrue(os.path.samefile(target + ".tmp", outside))
        self.assertEqual(
            [name for name in os.listdir(directory) if name.endswith(".tmp")],
            [os.path.basename(target) + ".tmp"],
        )


@unittest.skipIf(sys.platform == "win32", "POSIX 权限位")
class TestPosixPermissions(unittest.TestCase):

    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="zju-perm-")
        self.backup = os.path.join(self.workspace, "backups")
        self.login = os.path.join(self.workspace, "login")
        self.env = mock.patch.dict(
            os.environ,
            {
                "ZJU_BACKUP_DIR": self.backup,
                "ZJU_LOGIN_DIR": self.login,
                "ZJU_LOGIN_STORAGE": "memory",
            },
        )
        self.env.start()
        self.note = os.path.join(self.workspace, "讲义.md")
        with open(self.note, "w", encoding="utf-8") as handle:
            handle.write("# 旧讲义\n")

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_no_credential_file_is_left_behind(self):
        browser_login.save_session(COOKIE)
        self.assertFalse(os.path.exists(browser_login.session_file()))

    def test_backup_directory_and_file_permissions(self):
        path = note_lint.write_with_backup(self.note, "# 新讲义\n")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(stat.S_IMODE(os.stat(self.backup).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(self.note, encoding="utf-8") as handle:
            self.assertIn("新讲义", handle.read())

    def test_write_with_backup_refuses_a_symlinked_note(self):
        target = os.path.join(self.workspace, "real.md")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("# 真文件\n")
        link = os.path.join(self.workspace, "link.md")
        os.symlink(target, link)
        with self.assertRaises(OSError):
            note_lint.write_with_backup(link, "# 不应写入\n")
        with open(target, encoding="utf-8") as handle:
            self.assertIn("真文件", handle.read())
        self.assertFalse(os.path.isdir(self.backup) and os.listdir(self.backup))

    def test_backup_path_does_not_follow_a_planted_symlink(self):
        os.makedirs(self.backup, mode=0o700)
        outside = os.path.join(self.workspace, "outside.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("原始内容")
        # 备份名是随机后缀，预置链接已不可能命中；这里验证目录仍是私有的，
        # 且写入后没有把真实文件写穿到链接目标。
        planted = os.path.join(self.backup, "讲义.20260101-000000.deadbeef.bak")
        os.symlink(outside, planted)
        path = note_lint.write_with_backup(self.note, "# 新内容\n")
        self.assertNotEqual(path, planted)
        with open(outside, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "原始内容")


class TestStaleCookieCopySweep(unittest.TestCase):
    """A killed process must not leave a plaintext cookie DB in %TEMP%."""

    def _make_copy(self, age_seconds: int) -> str:
        directory = tempfile.mkdtemp(prefix="zju-lecture-cookie-")
        victim = os.path.join(directory, "Cookies")
        with open(victim, "wb") as handle:
            handle.write(b"cookie-row")
        stamp = time.time() - age_seconds
        os.utime(victim, (stamp, stamp))
        os.utime(directory, (stamp, stamp))
        return directory

    def test_an_old_private_copy_is_shredded(self):
        directory = self._make_copy(age_seconds=7200)
        try:
            cookies._sweep_stale_cookie_copies()
            self.assertFalse(os.path.exists(directory))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_a_fresh_copy_is_left_alone(self):
        directory = self._make_copy(age_seconds=0)
        try:
            cookies._sweep_stale_cookie_copies()
            self.assertTrue(os.path.isdir(directory))
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
