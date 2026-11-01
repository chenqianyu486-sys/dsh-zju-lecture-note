#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the 1.4.0 field report (v1.4.1).

Every test maps to one finding from ``docs/issue-1.4.0-实地运行反馈.md``:

* P1-1 ``zju_check_note`` resolved relative paths against the *server* cwd,
  not the session workspace, and never said where it looked;
* P1-2 ``fix=true`` did not repair ``display_not_isolated`` (59 unfixable
  errors on one real lecture note);
* P2-1 the lint report printed 91 findings one by one, burning context;
* P2-2 the "no cookie" slide branch mixed causes, had broken numbering and
  contradicted itself under Edge app-bound encryption;
* P2-3 the default ``知识总结.md`` silently overwrote an earlier lecture, and
  being git-ignored the loss was unrecoverable;
* P3-1 ``fix=true`` dropped a ``.bak`` next to the note and dirtied
  ``git status``;
* P3-2 the installed skill copy drifted (its front matter has no version) and
  the stale text told users to hand over a cookie;
* P3-3 the ASR had no quality signal, so a bad transcript was indistinguishable
  from a good one.
"""

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import mcp_server
from mcp_server import handle_tool_call
from zju_lecture import cookies as cookies_module
from zju_lecture.formatter import format_quality_line, transcript_quality
from zju_lecture.note_lint import check_markdown, fix_markdown, format_report
from zju_lecture.paths import (
    note_filename,
    note_target,
    resolve_path,
    sanitize_note_name,
)

SCRATCH_ROOT = os.path.join(BASE_DIR, "output", "test-tmp-v141")


def scratch(name):
    path = os.path.join(SCRATCH_ROOT, name)
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    return path


def glued_display_blocks(count=30):
    """A note where every ``$$`` block is glued to the surrounding prose."""
    parts = []
    for index in range(count):
        parts.append(f"第 {index} 段正文\n$$\nx_{index} = {index}\n$$\n下一段正文 {index}")
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------- P1-1


class TestWorkspacePathResolution(unittest.TestCase):
    """A note in the session workspace must be found by its relative name."""

    def setUp(self):
        self.workspace = scratch("workspace")
        self.elsewhere = scratch("elsewhere")
        self.note = os.path.join(self.workspace, "知识总结.md")
        with io.open(self.note, "w", encoding="utf-8") as handle:
            handle.write("# 标题\n\n正文 $x=1$。\n")

    def tearDown(self):
        shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)

    def _cwd_elsewhere(self):
        previous = os.getcwd()
        os.chdir(self.elsewhere)
        self.addCleanup(os.chdir, previous)

    def test_relative_path_resolves_through_the_session_workspace(self):
        self._cwd_elsewhere()
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": self.workspace}):
            resolved, tried = resolve_path("知识总结.md")
        self.assertEqual(resolved, os.path.abspath(self.note))
        self.assertTrue(tried)

    def test_check_note_accepts_a_relative_path(self):
        """The exact failure from the report: file exists, tool says it does not."""
        self._cwd_elsewhere()
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": self.workspace}):
            report = handle_tool_call("zju_check_note", {"file_path": "知识总结.md"})
        self.assertIn("讲义渲染规范检查", report)
        self.assertNotIn("找不到讲义文件", report)

    def test_missing_file_lists_the_paths_that_were_tried(self):
        self._cwd_elsewhere()
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": self.workspace}):
            report = handle_tool_call("zju_check_note", {"file_path": "不存在.md"})
        self.assertIn("找不到讲义文件", report)
        self.assertIn("已尝试", report)
        self.assertIn(os.path.abspath(self.workspace), report)

    def test_pwd_is_used_when_no_workspace_is_injected(self):
        self._cwd_elsewhere()
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": "", "PWD": self.workspace}):
            resolved, _tried = resolve_path("知识总结.md")
        self.assertEqual(resolved, os.path.abspath(self.note))

    def test_absolute_paths_are_never_rewritten(self):
        resolved, tried = resolve_path(self.note)
        self.assertEqual(resolved, os.path.abspath(self.note))
        self.assertEqual(tried, [os.path.abspath(self.note)])

    def test_courseware_extraction_accepts_a_relative_path(self):
        deck = os.path.join(self.workspace, "课件.md")
        with io.open(deck, "w", encoding="utf-8") as handle:
            handle.write("# 第一讲\n\n拉普拉斯变换\n")
        self._cwd_elsewhere()
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": self.workspace}):
            output = handle_tool_call("zju_extract_courseware", {"file_path": "课件.md"})
        self.assertIn("课件文件提取成功", output)
        self.assertIn("拉普拉斯变换", output)


# --------------------------------------------------------------------- P1-2


class TestDisplayIsolationAutofix(unittest.TestCase):
    """``fix=true`` must be able to repair the most common batch failure."""

    def test_blank_line_is_added_before_an_opening_block(self):
        fixed, applied = fix_markdown("正文\n$$\nx=1\n$$\n")
        self.assertIn("正文\n\n$$\nx=1\n$$", fixed)
        self.assertTrue(any("补全前后空行" in item for item in applied))

    def test_blank_line_is_added_after_a_closing_block(self):
        fixed, _applied = fix_markdown("$$\nx=1\n$$\n正文\n")
        self.assertIn("$$\n\n正文", fixed)

    def test_formula_body_is_never_padded_with_blank_lines(self):
        fixed, applied = fix_markdown("正文\n$$\na &= b + c\n\\\\\nd &= e\n$$\n正文\n")
        self.assertNotIn("a &= b + c\n\n", fixed)
        self.assertEqual(fixed.count("$$"), 2)
        self.assertTrue(applied)

    def test_fenced_examples_are_not_rewritten(self):
        text = "```\n正文\n$$\nx=1\n$$\n正文\n```\n"
        self.assertEqual(fix_markdown(text), (text, []))

    def test_list_indentation_is_preserved(self):
        text = "1. 第一步\n   $$\n   x=1\n   $$\n2. 第二步\n"
        fixed, applied = fix_markdown(text)
        self.assertIn("\n   $$\n", fixed)
        self.assertTrue(applied)
        # The block stays inside the list item instead of being cut out of it.
        self.assertIn("1. 第一步\n\n   $$", fixed)

    def test_a_full_batch_of_glued_blocks_becomes_clean(self):
        text = glued_display_blocks(30)
        self.assertEqual(
            len([i for i in check_markdown(text) if i.code == "display_not_isolated"]),
            60,
        )
        fixed, applied = fix_markdown(text)
        self.assertTrue(any("补全前后空行" in item for item in applied))
        remaining = [i.code for i in check_markdown(fixed) if i.level == "error"]
        self.assertEqual(remaining, [], "autofix did not clear display_not_isolated")

    def test_fixing_is_stable_and_idempotent(self):
        once, _ = fix_markdown(glued_display_blocks(5))
        twice, applied = fix_markdown(once)
        self.assertEqual(once, twice)
        self.assertEqual(applied, [])


# --------------------------------------------------------------------- P2-1


class TestAggregatedLintReport(unittest.TestCase):

    def test_identical_findings_are_grouped_once(self):
        issues = check_markdown(glued_display_blocks(30))
        report = format_report("note.md", issues)
        self.assertEqual(len(issues), 60)
        self.assertIn("display_not_isolated × 60", report)
        # 问题 / 修法 are printed once, not 60 times.
        self.assertEqual(report.count("问题:"), 1)
        self.assertEqual(report.count("修法:"), 1)
        self.assertLess(len(report), 1200, "聚合后的报告仍然过长:\n" + report)

    def test_line_list_is_bounded_and_explains_the_omission(self):
        issues = check_markdown(glued_display_blocks(30))
        report = format_report("note.md", issues, max_samples=2)
        self.assertIn("其余 58 处已省略", report)
        self.assertEqual(report.count("示例:"), 2)

    def test_max_samples_zero_prints_counts_only(self):
        issues = check_markdown(glued_display_blocks(3))
        report = format_report("note.md", issues, max_samples=0)
        self.assertIn("位置: 共 6 处", report)
        self.assertNotIn("示例:", report)

    def test_clean_note_still_reports_success(self):
        report = format_report("note.md", [])
        self.assertIn("结论: 通过", report)


# --------------------------------------------------------------------- P2-2


class TestSlideFailureMessage(unittest.TestCase):
    """One cause, one action — never a self-contradicting list."""

    def _slides_output(self, reason, detail="测试用原因"):
        with mock.patch.object(
            mcp_server, "_resolve_cookie", return_value=(None, detail, None, reason)
        ):
            return handle_tool_call("zju_fetch_slides", {"url_or_sub_id": "123456"})

    def test_abe_points_at_cookie_file_and_not_at_quitting_edge(self):
        output = self._slides_output("abe")
        self.assertIn("原因: abe", output)
        self.assertIn("ZJU_COOKIE_FILE", output)
        self.assertNotIn("后重试；本机 Edge 已启用", output)
        self.assertNotIn("2. 老师授课时", output)

    def test_locked_database_has_no_numbering_gaps(self):
        output = self._slides_output("locked")
        self.assertIn("原因: locked", output)
        self.assertIn("唯一可行动作", output)
        self.assertNotIn("2. 老师授课时", output)

    def test_degradation_hint_is_a_separate_sentence(self):
        output = self._slides_output("no_rows")
        self.assertIn("可平滑降级", output.split("唯一可行动作")[-1])

    def test_unrelated_causes_are_not_pasted_together(self):
        output = self._slides_output("abe")
        self.assertNotIn("老师授课时未通过智云课堂课件系统同步投影", output)

    def _edge_profile(self, name, abe):
        root = scratch(name)
        self.addCleanup(shutil.rmtree, root, True)
        with io.open(os.path.join(root, "Local State"), "w", encoding="utf-8") as handle:
            json.dump(
                {"os_crypt": {"app_bound_encrypted_key": "abc"} if abe else {"encrypted_key": "abc"}},
                handle,
            )
        network = os.path.join(root, "Profile 1", "Network")
        os.makedirs(network, exist_ok=True)
        connection = sqlite3.connect(os.path.join(network, "Cookies"))
        connection.execute(
            "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)"
        )
        connection.commit()
        connection.close()
        return root

    def _locked_read(self, root):
        with mock.patch.object(cookies_module, "_edge_root", return_value=root), \
             mock.patch.object(
                 cookies_module,
                 "_query_cookie_rows",
                 side_effect=cookies_module._DirectReadUnavailable("locked"),
             ), \
             mock.patch.object(
                 cookies_module.shutil, "copyfile",
                 side_effect=PermissionError(13, "Permission denied"),
             ):
            return cookies_module.read_edge_cookies("classroom.zju.edu.cn")

    def test_cookie_layer_marks_abe_instead_of_locked(self):
        """ABE is the decisive blocker; "quit Edge and retry" would be useless."""
        root = self._edge_profile("edge-abe", abe=True)
        cookie, error = self._locked_read(root)
        self.assertIsNone(cookie)
        self.assertEqual(error.reason, "abe")
        self.assertNotIn("后重试；本机 Edge 已启用", error.hint)

    def test_plain_locked_database_keeps_the_quit_edge_advice(self):
        root = self._edge_profile("edge-plain", abe=False)
        _cookie, error = self._locked_read(root)
        self.assertEqual(error.reason, "locked")
        self.assertIn("退出 Edge", error.hint)


# --------------------------------------------------------------------- P2-3


class TestCanonicalNoteNaming(unittest.TestCase):

    def setUp(self):
        self.workspace = scratch("notes")
        self.addCleanup(shutil.rmtree, SCRATCH_ROOT, ignore_errors=True)

    def _write(self, **extra):
        arguments = {
            "sub_id": "1988057",
            "slug": "复变函数",
            "content": "# 讲义\n\n正文 $x=1$。\n",
        }
        arguments.update(extra)
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": self.workspace}):
            return handle_tool_call("zju_write_note", arguments)

    def test_name_carries_the_sub_id(self):
        self.assertEqual(note_filename("1988057", "复变函数"), "知识总结-1988057-复变函数.md")
        self.assertEqual(note_filename("1988057"), "知识总结-1988057.md")

    def test_agent_chosen_name_wins(self):
        """The agent names the file from the lecture date and topic."""
        output = self._write(name="知识总结-2026-10-28-复变函数-保角映射与拉普拉斯变换")
        target = os.path.join(
            self.workspace, "知识总结-2026-10-28-复变函数-保角映射与拉普拉斯变换.md"
        )
        self.assertIn(target, output)
        self.assertTrue(os.path.isfile(target))
        self.assertNotIn("回退文件名", output)

    def test_agent_name_may_carry_the_extension(self):
        output = self._write(name="知识总结-2026-10-28-复变函数.md")
        self.assertIn("知识总结-2026-10-28-复变函数.md", output)
        self.assertNotIn("知识总结-2026-10-28-复变函数.md.md", output)

    def test_unsafe_characters_in_an_agent_name_are_stripped(self):
        output = self._write(name='知识总结 a/b\\c:d*e?f"g<h>i|j')
        target = os.path.join(self.workspace, "知识总结-a-b-c-d-e-f-g-h-i-j.md")
        self.assertIn(target, output)
        self.assertTrue(os.path.isfile(target))

    def test_an_absurdly_long_name_is_truncated(self):
        output = self._write(name="知识总结-" + "长" * 200)
        written = [
            name for name in os.listdir(self.workspace) if name.startswith("知识总结-")
        ]
        self.assertEqual(len(written), 1)
        self.assertLessEqual(len(written[0]), 84, written[0])
        self.assertTrue(output.startswith("=== 已写入讲义 ==="))

    def test_missing_name_falls_back_and_says_so(self):
        """No name -> sub_id fallback, plus a nudge to name by date + topic."""
        output = self._write()
        self.assertIn("知识总结-1988057-复变函数.md", output)
        self.assertIn("回退文件名", output)
        self.assertIn("name=知识总结-<上课日期>", output)

    def test_two_lectures_of_one_course_do_not_collide(self):
        first = self._write(name="知识总结-2026-10-21-复变函数-分式线性映射")
        second = self._write(
            sub_id="1988617", name="知识总结-2026-10-28-复变函数-保角映射"
        )
        self.assertIn("已写入讲义", first)
        self.assertIn("已写入讲义", second)
        self.assertEqual(
            sorted(name for name in os.listdir(self.workspace) if name.endswith(".md")),
            ["知识总结-2026-10-21-复变函数-分式线性映射.md", "知识总结-2026-10-28-复变函数-保角映射.md"],
        )

    def test_same_agent_name_is_refused_rather_than_overwritten(self):
        self._write(name="知识总结-2026-10-28-复变函数-保角映射")
        second = self._write(name="知识总结-2026-10-28-复变函数-保角映射")
        self.assertIn("未写入：同名讲义已存在", second)
        self.assertIn("name", second)

    def test_write_creates_the_canonical_file(self):
        output = self._write()
        target = os.path.join(self.workspace, "知识总结-1988057-复变函数.md")
        self.assertIn(target, output)
        self.assertTrue(os.path.isfile(target))
        self.assertIn("讲义渲染规范检查", output)

    def test_a_second_lecture_never_overwrites_the_first(self):
        first = self._write()
        self.assertIn("已写入讲义", first)
        second = self._write()
        self.assertIn("未写入：同名讲义已存在", second)
        self.assertIn("overwrite=true", second)
        with io.open(
            os.path.join(self.workspace, "知识总结-1988057-复变函数.md"), encoding="utf-8"
        ) as handle:
            self.assertIn("# 讲义", handle.read())

    def test_a_different_slug_is_a_different_file(self):
        self._write()
        output = self._write(slug="积分变换")
        self.assertIn("知识总结-1988057-积分变换.md", output)

    def test_overwrite_is_explicit_and_backed_up(self):
        self._write()
        backup_dir = scratch("note-backups")
        with mock.patch.dict(
            os.environ, {"ZJU_WORKSPACE": self.workspace, "ZJU_BACKUP_DIR": backup_dir}
        ):
            output = handle_tool_call(
                "zju_write_note",
                {
                    "sub_id": "1988057",
                    "slug": "复变函数",
                    "content": "# 新讲义\n",
                    "overwrite": True,
                },
            )
        self.assertIn("已写入讲义", output)
        self.assertEqual(len(os.listdir(backup_dir)), 1)

    def test_writes_are_confined_to_the_workspace(self):
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": self.workspace}):
            target, error = note_target("1988057", "x", directory="..")
        self.assertIsNone(target)
        self.assertIn("工作区之外", error or "")

    def test_absolute_directory_outside_the_workspace_is_refused(self):
        outside = scratch("outside")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": self.workspace}):
            target, error = note_target("1988057", "x", directory=outside)
        self.assertIsNone(target)
        self.assertIn("工作区之外", error or "")

    def test_unsafe_slug_characters_are_stripped(self):
        name = note_filename("1988057", 'a/b\\c:d*e?f"g<h>i|j')
        self.assertNotRegex(name, r'[\\/:*?"<>|]')
        self.assertTrue(name.endswith(".md"))

    def test_sanitize_note_name_keeps_the_stem_only(self):
        self.assertEqual(sanitize_note_name("知识总结-2026-10-28-复变函数.md"), "知识总结-2026-10-28-复变函数")
        self.assertEqual(sanitize_note_name("  知识总结   2026 复变函数  "), "知识总结-2026-复变函数")
        self.assertEqual(sanitize_note_name("../.."), "")
        self.assertEqual(sanitize_note_name(""), "")

    def test_missing_content_is_rejected(self):
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": self.workspace}):
            with self.assertRaises(ValueError):
                handle_tool_call("zju_write_note", {"sub_id": "1", "content": "  "})


# --------------------------------------------------------------------- P3-1


class TestBackupLocation(unittest.TestCase):

    def test_backup_does_not_land_next_to_the_note(self):
        workspace = scratch("backup")
        note = os.path.join(workspace, "note.md")
        with io.open(note, "w", encoding="utf-8") as handle:
            handle.write("正文\n$$\n\\frac12\n$$\n")
        backup_dir = scratch("backup-store")
        with mock.patch.dict(os.environ, {"ZJU_BACKUP_DIR": backup_dir}):
            report = handle_tool_call("zju_check_note", {"file_path": note, "fix": True})
        self.assertFalse(os.path.exists(note + ".bak"))
        self.assertIn("已自动修复", report)
        self.assertIn(backup_dir, report)
        self.assertEqual(len(os.listdir(backup_dir)), 1)
        shutil.rmtree(SCRATCH_ROOT, ignore_errors=True)


class TestEntrypointWorkspaceWiring(unittest.TestCase):
    """The JS half must hand the session workspace to the Python child."""

    def _source(self, *parts):
        with io.open(os.path.join(BASE_DIR, *parts), encoding="utf-8") as handle:
            return handle.read()

    def test_entrypoint_reads_the_session_working_directory(self):
        source = self._source("lib", "index.js")
        self.assertIn('ctx.get("workingDirectory")', source)
        self.assertIn("session.header", source)
        self.assertIn("bridge.useWorkspace(sessionCwd(ctx, exec))", source)

    def test_bridge_exports_the_workspace_to_the_child(self):
        source = self._source("lib", "bridge.js")
        self.assertIn("ZJU_WORKSPACE", source)
        self.assertIn("useWorkspace(", source)
        # A workspace change may only recycle the child while it is idle.
        self.assertIn("this.pending.size > 0", source)

    def test_write_note_is_presented_as_an_edit_tool(self):
        source = self._source("lib", "index.js")
        self.assertIn("zju_write_note:", source)
        self.assertIn("自动命名 + 写后校验", source)


# --------------------------------------------------------------------- P3-2


class TestSkillDriftGuard(unittest.TestCase):

    SKILL = os.path.join(BASE_DIR, "skills", "zju-lecture-summarizer", "SKILL.md")
    MANIFEST = os.path.join(BASE_DIR, "skills", "zju-lecture-summarizer.manifest.json")

    def _skill_text(self):
        with io.open(self.SKILL, encoding="utf-8") as handle:
            return handle.read()

    def test_skill_never_tells_anyone_to_hand_over_a_cookie(self):
        text = self._skill_text()
        for forbidden in (
            "手动提供 cookie",
            "手动提供 Cookie",
            "让用户手动提供",
            "请用户提供 Cookie",
            "提供 cookie 参数",
        ):
            self.assertNotIn(forbidden, text, f"Skill 里仍有过期文案: {forbidden}")

    def test_skill_states_the_privacy_guardrail(self):
        text = self._skill_text()
        self.assertIn("不要让用户把 Cookie 粘贴进对话", text)

    def test_manifest_hash_matches_the_shipped_skill(self):
        with open(self.SKILL, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        with io.open(self.MANIFEST, encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["contentHash"], f"sha256:{digest}")
        self.assertEqual(manifest["files"][0]["sha256"], digest)

    def test_manifest_version_follows_the_package(self):
        with io.open(os.path.join(BASE_DIR, "package.json"), encoding="utf-8") as handle:
            version = json.load(handle)["version"]
        with io.open(self.MANIFEST, encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["version"], version)

    def test_skill_documents_the_canonical_file_name_and_writer(self):
        text = self._skill_text()
        self.assertIn("zju_write_note", text)
        self.assertIn("知识总结-<sub_id>", text)

    def test_entrypoint_warns_with_content_hashes(self):
        with io.open(os.path.join(BASE_DIR, "lib", "index.js"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("createHash", source)
        self.assertIn("内容哈希", source)


# --------------------------------------------------------------------- P3-3


class TestTranscriptQualitySignal(unittest.TestCase):

    CLEAN = [
        {"begin_sec": index * 20, "text": "今天我们讲解拉普拉斯变换的定义与收敛域，并给出右半平面的判据。"}
        for index in range(50)
    ]
    NOISY = [
        {"begin_sec": 64, "text": "第7章题目叫拉普拉斯变换。病患love plus数学家病患，那到底是个啥病患呢？"},
        {"begin_sec": 39, "text": "无穷远点对应的是什么点N趋向于无穷啊。懂我有无交易的是不是东西到圆顶啊"},
        {"begin_sec": 83, "text": "哎，S最后的结论是这个结论啊，又半个平米啊"},
        {"begin_sec": 84, "text": "嗯"},
        {"begin_sec": 85, "text": "这个"},
    ]

    def test_clean_transcript_scores_high(self):
        quality = transcript_quality(self.CLEAN)
        self.assertEqual(quality["reliability"], "high")
        self.assertEqual(quality["noise_ratio"], 0.0)

    def test_noisy_transcript_scores_low_and_names_the_fillers(self):
        quality = transcript_quality(self.NOISY)
        self.assertEqual(quality["reliability"], "low")
        self.assertTrue(quality["top_fillers"])
        self.assertIn("不要照字面直译", quality["hint"])

    def test_empty_transcript_is_reported_as_unknown(self):
        self.assertEqual(transcript_quality([])["reliability"], "unknown")

    def test_quality_line_is_compact(self):
        line = format_quality_line(transcript_quality(self.CLEAN))
        self.assertIn("ASR 可靠度: 高", line)
        self.assertLess(len(line), 200)

    def test_transcript_header_carries_the_quality_signal(self):
        segments = self.NOISY
        with mock.patch.object(
            mcp_server, "fetch_transcript", side_effect=lambda sub_id, tenant: segments
        ):
            output = mcp_server._dispatch_tool(
                "zju_fetch_transcript", {"url_or_sub_id": "123456"}
            )
        self.assertIn("ASR 可靠度", output)
        self.assertIn("ASR 可靠度: 低", output)

    def test_json_view_carries_the_quality_object(self):
        with mock.patch.object(
            mcp_server, "fetch_transcript", side_effect=lambda sub_id, tenant: self.NOISY
        ):
            payload = json.loads(
                mcp_server._dispatch_tool(
                    "zju_fetch_transcript",
                    {"url_or_sub_id": "123456", "view_format": "json"},
                )
            )
        self.assertEqual(payload["quality"]["reliability"], "low")

    def test_chunked_view_carries_the_quality_object(self):
        with mock.patch.object(
            mcp_server, "fetch_transcript", side_effect=lambda sub_id, tenant: self.NOISY
        ):
            payload = json.loads(
                mcp_server._dispatch_tool(
                    "zju_fetch_transcript",
                    {"url_or_sub_id": "123456", "view_format": "chunked", "max_chars": 1200},
                )
            )
        self.assertIn("quality", payload)
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False)), 1400)


class TestNotesStayOutOfTheRepo(unittest.TestCase):
    """讲义是本机学习材料，插件写出的文件不能被提交进仓库。

    这一条对插件作者本人同样成立：他在这个仓库里跑插件时，讲义也不该出现在
    `git status` 里。任何层级的 ``知识总结*.md`` 与推荐的 ``notes/`` 目录都要被忽略。
    """

    def test_gitignore_covers_generated_notes(self):
        with io.open(os.path.join(BASE_DIR, ".gitignore"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("知识总结*.md", text, "任意层级的讲义都要被忽略")
        self.assertIn("/notes/", text, "推荐的 notes/ 目录要被忽略")

    def _check_ignore(self, relative):
        try:
            completed = subprocess.run(
                ["git", "check-ignore", "-q", relative],
                cwd=BASE_DIR,
                capture_output=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            self.skipTest("本机没有可用的 git")
        return completed.returncode == 0

    def test_a_generated_note_is_ignored_in_the_workspace_root(self):
        self.assertTrue(
            self._check_ignore("知识总结-2026-10-28-复变函数-保角映射.md"),
            "根目录的讲义没有被 .gitignore 挡住",
        )

    def test_notes_subdirectory_is_ignored(self):
        self.assertTrue(self._check_ignore("notes/知识总结-2026-10-28.md"), "notes/ 没有被挡住")
        self.assertTrue(self._check_ignore("notes/随手笔记.md"), "notes/ 下任意文件都要被挡住")


if __name__ == "__main__":
    unittest.main()
