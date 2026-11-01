#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the review batch on top of 1.3.3 (v1.4.0).

Every test here maps to one finding from the review issue:

1. autofix rewrote inline-code examples;
2. ``fix=true`` overwrote the note without a backup;
3. DOCX extraction dropped paragraph breaks;
4. ``chunked`` / ``json`` views ignored ``max_chars``;
5. a sliced transcript reported the slice as the course duration;
6. Edge app-bound encryption (ABE) turned "quit Edge and retry" into a dead end;
7. the cookie-DB copy dropped the WAL sidecars;
8. ``config.json`` was refused as a sensitive file;
9. PDF failures leaked raw parser exceptions without naming the interpreter;
10. a timeout killed the Python child even with other calls in flight;
11. the system prompt section was injected unconditionally.
"""

import io
import json
import os
import shutil
import sqlite3
import sys
import unittest
import zipfile
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import mcp_server
from zju_lecture import cookies as cookies_module
from zju_lecture.courseware import CoursewareError, _extract_docx, extract_courseware_text
from zju_lecture.note_lint import fix_markdown
from zju_lecture.security import LocalFileError, guard_local_file

SCRATCH_ROOT = os.path.join(BASE_DIR, "output", "test-tmp")


def scratch(name):
    """Workspace-local temp dir.

    The DSH sandbox refuses writes to %TEMP%, so tests use a git-ignored
    folder under ``output/`` and clean it up themselves.
    """
    path = os.path.join(SCRATCH_ROOT, name)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    return path


def fake_segments(count=400, step=20):
    return [
        {"begin_sec": i * step, "text": "这是第%d句字幕内容，用来撑长度。" % i}
        for i in range(count)
    ]


class TestNoteAutofix(unittest.TestCase):

    def test_inline_code_examples_are_never_rewritten(self):
        source = "示例：`\\frac12` 与 `\\dfrac{a}{b}` 应保持原样。\n"
        fixed, applied = fix_markdown(source)
        self.assertEqual(fixed, source)
        self.assertEqual(applied, [])

    def test_real_formulas_are_still_fixed(self):
        fixed, applied = fix_markdown("公式 $\\frac12$ 与 $\\dfrac{a}{b}$。\n")
        self.assertIn("$\\frac{1}{2}$", fixed)
        self.assertIn("$\\frac{a}{b}$", fixed)
        self.assertTrue(applied)

    def test_table_pipes_inside_code_spans_are_left_alone(self):
        line = "| `$|x|=1$` | $|y|=2$ |\n"
        fixed, _applied = fix_markdown(line)
        self.assertIn("`$|x|=1$`", fixed)
        self.assertIn("\\lvert y\\rvert", fixed)

    def test_unclosed_backtick_disables_fixing_for_the_tail(self):
        source = "前言 `\\frac12 未闭合\n"
        fixed, _applied = fix_markdown(source)
        self.assertEqual(fixed, source)


class TestCheckNoteWriteback(unittest.TestCase):

    def setUp(self):
        self.dir = scratch("check-note")
        self.note = os.path.join(self.dir, "note.md")
        with io.open(self.note, "w", encoding="utf-8") as handle:
            handle.write("单行公式 $$\\frac12$$\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_fix_creates_a_backup_before_overwriting(self):
        backup_dir = scratch("check-note-backups")
        self.addCleanup(shutil.rmtree, backup_dir, ignore_errors=True)
        with mock.patch.dict(os.environ, {"ZJU_BACKUP_DIR": backup_dir}):
            report = mcp_server._dispatch_tool(
                "zju_check_note", {"file_path": self.note, "fix": True}
            )
        backups = os.listdir(backup_dir)
        self.assertEqual(len(backups), 1, "缺少备份文件")
        backup = os.path.join(backup_dir, backups[0])
        with io.open(backup, encoding="utf-8") as handle:
            self.assertIn("$$\\frac12$$", handle.read())
        # P3-1: the backup no longer lands next to the note, so `git status`
        # stays clean.
        self.assertFalse(os.path.exists(self.note + ".bak"), "备份不应落在讲义旁边")
        self.assertIn(backup, report)
        with io.open(self.note, encoding="utf-8") as handle:
            self.assertIn("\\frac{1}{2}", handle.read())

    def test_no_backup_when_nothing_needed_fixing(self):
        clean = os.path.join(self.dir, "clean.md")
        with io.open(clean, "w", encoding="utf-8") as handle:
            handle.write("# 干净讲义\n")
        backup_dir = scratch("check-note-backups-none")
        self.addCleanup(shutil.rmtree, backup_dir, ignore_errors=True)
        with mock.patch.dict(os.environ, {"ZJU_BACKUP_DIR": backup_dir}):
            mcp_server._dispatch_tool("zju_check_note", {"file_path": clean, "fix": True})
        self.assertFalse(os.path.exists(clean + ".bak"))
        self.assertEqual(os.listdir(backup_dir), [])


class TestDocxExtraction(unittest.TestCase):

    def setUp(self):
        self.dir = scratch("docx")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _make_docx(self, body):
        path = os.path.join(self.dir, "deck.docx")
        xml = '<w:document><w:body>%s</w:body></w:document>' % body
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", xml)
        return path

    def test_paragraphs_keep_their_breaks(self):
        path = self._make_docx(
            "<w:p><w:r><w:t>第一段内容</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>第二段内容</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>第三段内容</w:t></w:r></w:p>"
        )
        self.assertEqual(_extract_docx(path), "第一段内容\n第二段内容\n第三段内容")

    def test_tabs_line_breaks_and_entities_survive(self):
        path = self._make_docx(
            "<w:p><w:r><w:t>列1</w:t><w:tab/><w:t>列2</w:t><w:br/>"
            "<w:t>a &amp; b</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>第二段</w:t></w:r></w:p>"
        )
        text = _extract_docx(path)
        self.assertIn("\t", text)
        self.assertIn("a & b", text)
        self.assertGreaterEqual(text.count("\n"), 2)


class TestTranscriptBudget(unittest.TestCase):

    def setUp(self):
        self.segments = fake_segments()
        patcher = mock.patch.object(
            mcp_server, "fetch_transcript", side_effect=lambda sub_id, tenant: self.segments
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    def _call(self, **kwargs):
        arguments = {"url_or_sub_id": "123456"}
        arguments.update(kwargs)
        return mcp_server._dispatch_tool("zju_fetch_transcript", arguments)

    def test_chunked_view_respects_max_chars(self):
        text = self._call(view_format="chunked", max_chars=1000)
        self.assertLessEqual(len(text), 1000)
        payload = json.loads(text)
        self.assertTrue(payload["truncated"])
        self.assertLess(payload["returned_chunks"], payload["total_chunks"])

    def test_json_view_respects_max_chars(self):
        text = self._call(view_format="json", max_chars=1000)
        self.assertLessEqual(len(text), 1000)
        payload = json.loads(text)
        self.assertTrue(payload["truncated"])
        self.assertIsNotNone(payload["next_start_minute"])

    def test_slice_reports_full_duration_and_slice_range(self):
        text = self._call(view_format="per_minute", start_minute=100, end_minute=104)
        self.assertIn("课程总时长: ~02:13:00", text)
        self.assertIn("本次区间: 01:40:00-01:44:40", text)
        self.assertNotIn("课程总时长: ~01:44:40", text)


class TestCookieHandling(unittest.TestCase):

    def setUp(self):
        self.dir = scratch("cookies")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_copy_replays_wal_and_cleans_up(self):
        db_path = os.path.join(self.dir, "Cookies")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)"
        )
        conn.execute(
            "INSERT INTO cookies VALUES ('classroom.zju.edu.cn', 'SESSDATA', 'plain-value', X'')"
        )
        conn.commit()
        # The sandbox blocks %TEMP%, so the private copy dir is rooted here.
        counter = {"n": 0}

        def mkdtemp(prefix="zju-lecture-cookie-"):
            counter["n"] += 1
            path = os.path.join(self.dir, "%s%d" % (prefix, counter["n"]))
            os.makedirs(path, exist_ok=True)
            return path

        try:
            with mock.patch.object(cookies_module.tempfile, "mkdtemp", side_effect=mkdtemp):
                rows = cookies_module._read_rows_with_copy(db_path, "classroom.zju.edu.cn")
        finally:
            conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "plain-value")
        leftovers = [name for name in os.listdir(self.dir) if name.startswith("zju-lecture-cookie-")]
        self.assertEqual(leftovers, [], "临时 Cookie 副本未清理")

    def test_app_bound_encryption_is_detected(self):
        edge_root = os.path.join(self.dir, "Edge")
        os.makedirs(edge_root, exist_ok=True)
        with io.open(os.path.join(edge_root, "Local State"), "w", encoding="utf-8") as handle:
            json.dump({"os_crypt": {"app_bound_encrypted_key": "abc"}}, handle)
        with mock.patch.object(cookies_module, "_edge_root", return_value=edge_root):
            self.assertTrue(cookies_module._edge_app_bound_enabled())

    def test_plain_edge_reports_no_app_bound(self):
        edge_root = os.path.join(self.dir, "Edge")
        os.makedirs(edge_root, exist_ok=True)
        with io.open(os.path.join(edge_root, "Local State"), "w", encoding="utf-8") as handle:
            json.dump({"os_crypt": {"encrypted_key": "abc"}}, handle)
        with mock.patch.object(cookies_module, "_edge_root", return_value=edge_root):
            self.assertFalse(cookies_module._edge_app_bound_enabled())


class TestSensitiveNames(unittest.TestCase):

    def setUp(self):
        self.dir = scratch("sensitive")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _touch(self, name, text="x"):
        path = os.path.join(self.dir, name)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_generic_config_json_is_allowed(self):
        path = self._touch("config.json", "{}")
        self.assertEqual(guard_local_file(path, {".json"}), os.path.realpath(path))

    def test_academic_names_are_allowed(self):
        for name in ("secret sharing 第5章.md", "private equity 笔记.md"):
            path = self._touch(name)
            self.assertEqual(guard_local_file(path, {".md"}), os.path.realpath(path), name)

    def test_credential_like_names_are_still_refused(self):
        for name in ("my-secret.txt", "client_secret.json", "credentials.md", "token.json"):
            path = self._touch(name)
            with self.assertRaises(LocalFileError, msg=name):
                guard_local_file(path, {".txt", ".json", ".md"})


class TestPdfErrors(unittest.TestCase):

    def setUp(self):
        self.dir = scratch("pdf")
        self.pdf = os.path.join(self.dir, "broken.pdf")
        with open(self.pdf, "wb") as handle:
            handle.write(b"%PDF-1.4\nbroken\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_error_names_the_interpreter_and_the_attempts(self):
        with self.assertRaises(CoursewareError) as caught:
            extract_courseware_text(self.pdf)
        message = str(caught.exception)
        self.assertIn(sys.executable, message)
        self.assertIn("pypdf", message)


class TestStaticPluginWiring(unittest.TestCase):
    """Checks that live in JS files the Python suite cannot import."""

    def setUp(self):
        self.root = BASE_DIR

    def _read(self, *parts):
        with io.open(os.path.join(self.root, *parts), encoding="utf-8") as handle:
            return handle.read()

    def test_system_prompt_declares_its_scope(self):
        source = self._read("lib", "index.js")
        self.assertIn("适用范围", source)
        self.assertIn("其他任务请忽略本段", source)

    def test_check_note_is_presented_as_an_edit_tool(self):
        source = self._read("lib", "index.js")
        self.assertIn('zju_check_note: { title: "检查/修正讲义渲染规范", kind: "edit" }', source)

    def test_bridge_only_recycles_the_child_when_idle(self):
        source = self._read("lib", "bridge.js")
        self.assertIn("this.pending.size === 0", source)


if __name__ == "__main__":
    unittest.main()
