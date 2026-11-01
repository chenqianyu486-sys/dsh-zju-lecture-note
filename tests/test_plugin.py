#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression tests for the ZJU Lecture agent plugin.

Covered:
* URL parsing, timestamp formatting, segment filtering
* chunk time-span formatting (regression: the span used to roll over wrongly)
* courseware extraction
* MCP tool dispatch and schema sanity
* MCP stdio protocol round-trip (initialize / tools/list / tools/call / notifications)
* FIPS-197 known-answer test for the ported AES-128 decryptor
* Edge cookie failure classification (locked vs. no rows)
"""

import json
import os
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from zju_lecture.client import _SameHostRedirectHandler, create_ssl_context, parse_lecture_url
from zju_lecture.cookies import (
    _aes128_decrypt_block,
    _DirectReadUnavailable,
    _host_matches,
    _key_expansion,
    read_edge_cookies,
)
from zju_lecture.formatter import (
    build_transcript_views,
    chunk_transcript,
    filter_segments,
    format_minute_span,
    format_timestamp,
)
from zju_lecture.courseware import CoursewareError, extract_courseware_text
from zju_lecture.note_lint import check_markdown, fix_markdown
from zju_lecture.security import (
    REDACTOR,
    REDACTED,
    SecretRedactor,
    guard_local_file,
    mask_cookie_header,
    sanitize_cookie_header,
)
import mcp_server
from mcp_server import TOOLS, handle_request, handle_tool_call


class TestFormatters(unittest.TestCase):

    def test_parse_lecture_url(self):
        res1 = parse_lecture_url(
            "https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456&tenant_code=112"
        )
        self.assertEqual(res1["course_id"], "58133")
        self.assertEqual(res1["sub_id"], "123456")
        self.assertEqual(res1["tenant_code"], "112")

        res2 = parse_lecture_url("987654")
        self.assertEqual(res2["sub_id"], "987654")
        self.assertEqual(res2["tenant_code"], "112")

        with self.assertRaises(Exception):
            parse_lecture_url("")

    def test_format_timestamp(self):
        self.assertEqual(format_timestamp(0), "00:00:00")
        self.assertEqual(format_timestamp(65), "00:01:05")
        self.assertEqual(format_timestamp(3665), "01:01:05")

    def test_transcript_formatting_and_chunking(self):
        segments = [
            {"begin_sec": 10, "text": "各位同学大家早上好。"},
            {"begin_sec": 45, "text": "今天我们讲解霍夫曼树。"},
            {"begin_sec": 70, "text": "首先看霍夫曼编码的定义。"},
            {"begin_sec": 130, "text": "其时间复杂度为 O(N log N)。"},
        ]
        per_seg, per_min, minutes_map = build_transcript_views(segments)

        self.assertIn("[00:00:10] 各位同学大家早上好。", per_seg)
        self.assertIn("[00:00] 各位同学大家早上好。今天我们讲解霍夫曼树。", per_min)
        self.assertIn("[00:01] 首先看霍夫曼编码的定义。", per_min)
        self.assertIn("[00:02] 其时间复杂度为 O(N log N)。", per_min)

        chunks = chunk_transcript(minutes_map, max_chars=50)
        self.assertTrue(len(chunks) >= 1)
        self.assertIn("text", chunks[0])

    def test_minute_span_does_not_roll_over(self):
        """The span must end at the END of the last minute, not wrap around."""
        self.assertEqual(format_minute_span(0, 0), "00:00-00:01")
        self.assertEqual(format_minute_span(59, 59), "00:59-01:00")
        self.assertEqual(format_minute_span(60, 60), "01:00-01:01")

        chunks = chunk_transcript({59: ["x" * 10], 60: ["y" * 10]})
        self.assertEqual(chunks[0]["time_span"], "00:59-01:01")

        chunks = chunk_transcript({59: ["x" * 10]})
        self.assertEqual(chunks[0]["time_span"], "00:59-01:00")

    def test_filter_segments(self):
        segments = [
            {"begin_sec": 10, "text": "A"},
            {"begin_sec": 70, "text": "B"},
            {"begin_sec": 150, "text": "C"},
        ]
        filtered = filter_segments(segments, start_sec=60, end_sec=100)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["text"], "B")


class TestCourseware(unittest.TestCase):

    def test_courseware_extraction(self):
        test_file = os.path.join(tempfile.gettempdir(), "zju_sample_test.md")
        with open(test_file, "w", encoding="utf-8") as handle:
            handle.write("# 算法设计与分析\n\n- 动态规划\n- 贪心算法\n")
        try:
            text = extract_courseware_text(test_file)
            self.assertIn("动态规划", text)
            self.assertIn("贪心算法", text)
        finally:
            if os.path.exists(test_file):
                os.unlink(test_file)

    def test_unsupported_format_raises(self):
        with self.assertRaises(Exception):
            extract_courseware_text(os.path.join(tempfile.gettempdir(), "nope.xyz"))


class TestNoteLint(unittest.TestCase):
    """The note linter must catch exactly the things that break rendering."""

    CLEAN = (
        "# 标题\n"
        "\n"
        "正文 $E=mc^2$ 结束。\n"
        "\n"
        "| 列 A | 列 B |\n"
        "| :--- | :--- |\n"
        "| $x=1$ | $\\lvert y\\rvert=2$ |\n"
        "\n"
        "$$\n"
        "f(x)=\\frac{1}{2}x\n"
        "$$\n"
        "\n"
        "结尾 $\\mathrm{i}$。\n"
    )

    def _codes(self, text):
        return {issue.code for issue in check_markdown(text)}

    def _errors(self, text):
        return [i for i in check_markdown(text) if i.level == "error"]

    def test_clean_note_has_no_findings(self):
        issues = check_markdown(self.CLEAN)
        self.assertEqual([i.code for i in issues], [], f"clean note flagged: {issues}")

    def test_bare_pipe_in_table_cell_is_an_error(self):
        """A bare ``|`` inside a table formula silently cuts the column in half."""
        text = (
            "| 时间段 | 要点 |\n"
            "| :--- | :--- |\n"
            "| `00:03` | 用 $e^z$ 的 $|w|=e^x$ 做分析 |\n"
        )
        self.assertIn("table_bare_pipe", self._codes(text))
        self.assertTrue(self._errors(text))

    def test_lvert_avoids_the_table_trap(self):
        text = (
            "| 时间段 | 要点 |\n"
            "| :--- | :--- |\n"
            "| `00:03` | 用 $e^z$ 的 $\\lvert w\\rvert=e^x$ 做分析 |\n"
        )
        self.assertNotIn("table_bare_pipe", self._codes(text))
        self.assertEqual(self._errors(text), [])

    def test_unclosed_inline_math_is_an_error(self):
        self.assertIn("inline_math_unclosed", self._codes("公式写成 $x=1 就不对了。\n"))

    def test_frac_requires_braces_on_both_sides(self):
        self.assertIn("frac_no_brace", self._codes("写成 $\\frac12$ 不行。\n"))
        self.assertIn("frac_no_brace", self._codes("写成 $\\frac{1}2$ 不行。\n"))
        self.assertNotIn("frac_no_brace", self._codes("写成 $\\frac{1}{2}$ 可以。\n"))

    def test_display_block_must_be_isolated(self):
        glued = "上句\n$$\nx=1\n$$\n下句\n"
        self.assertIn("display_not_isolated", self._codes(glued))
        self.assertIn("display_inline", self._codes("写成 $$x=1$$ 不行。\n"))

    def test_unclosed_display_block_is_an_error(self):
        self.assertIn("display_unclosed", self._codes("$$\nx=1\n"))

    def test_single_line_details_is_an_error(self):
        text = "<details><summary>答案</summary>正文</details>\n"
        self.assertIn("details_single_line", self._codes(text))

    def test_multiline_details_is_accepted(self):
        text = (
            "<details>\n"
            "<summary>答案</summary>\n"
            "\n"
            "正文 $x=1$\n"
            "\n"
            "</details>\n"
        )
        self.assertEqual(self._errors(text), [])

    def test_dfrac_is_a_warning_not_an_error(self):
        issues = check_markdown("写成 $\\dfrac{1}{2}$ 不统一。\n")
        self.assertIn("dfrac_used", {i.code for i in issues})
        self.assertEqual([i for i in issues if i.level == "error"], [])

    def test_bare_imaginary_unit_is_a_warning(self):
        issues = check_markdown("写成 $i\\mapsto\\frac{1}{2}$ 不统一。\n")
        self.assertIn("bare_imaginary_unit", {i.code for i in issues})

    def test_code_fence_contents_are_not_linted(self):
        text = "```\n| $x$ | $y$ |\n| $a$ | $b$ |\n```\n"
        self.assertEqual(self._errors(text), [])

    def test_fixer_repairs_the_real_failure_modes(self):
        broken = (
            "| A | B |\n"
            "| :--- | :--- |\n"
            "| $x$ | $|y|=1$ |\n"
            "\n"
            "$$z=\\frac12$$\n"
            "\n"
            "<details><summary>答案</summary>正文 $x$</details>\n"
        )
        fixed, applied = fix_markdown(broken)
        self.assertTrue(applied)
        self.assertIn("\\lvert y\\rvert", fixed)
        self.assertIn("\\frac{1}{2}", fixed)
        self.assertIn("<details>\n", fixed)
        errors = [i for i in check_markdown(fixed) if i.level == "error"]
        self.assertEqual([i.code for i in errors], [], f"still broken: {errors}")

    def test_fixer_leaves_code_fences_alone(self):
        text = "```\n$$z=\\frac12$$\n```\n"
        fixed, applied = fix_markdown(text)
        self.assertEqual(fixed, text)
        self.assertEqual(applied, [])

    def test_fixer_does_not_touch_a_clean_note(self):
        fixed, applied = fix_markdown(self.CLEAN)
        self.assertEqual(fixed, self.CLEAN)
        self.assertEqual(applied, [])


class TestPackaging(unittest.TestCase):

    def test_package_collects_init_and_skips_bytecode(self):
        """``__init__.py`` must ship; ``__pycache__`` must not."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "build_plugin",
            os.path.join(BASE_DIR, "tools", "build_plugin.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        collected = module.collect_package_files()
        self.assertIn("zju_lecture/__init__.py", collected)
        self.assertIn("zju_lecture/note_lint.py", collected)
        self.assertNotIn("zju_lecture/__pycache__", collected)
        self.assertFalse([f for f in collected if "__pycache__" in f])


class TestMCPTools(unittest.TestCase):

    def test_tool_schemas_are_wellformed(self):
        names = [tool["name"] for tool in TOOLS]
        for expected in (
            "zju_parse_url",
            "zju_fetch_transcript",
            "zju_fetch_slides",
            "zju_extract_courseware",
            "zju_get_video_url",
            "zju_read_browser_cookie",
            "zju_check_note",
        ):
            self.assertIn(expected, names)

        for tool in TOOLS:
            self.assertTrue(tool["name"].startswith("zju_"))
            self.assertTrue(tool["description"].strip())
            schema = tool["inputSchema"]
            self.assertEqual(schema.get("type"), "object")
            self.assertIsInstance(schema.get("properties"), dict)
            for required in schema.get("required", []):
                self.assertIn(required, schema["properties"])

    def test_mcp_tool_dispatch(self):
        url = "https://classroom.zju.edu.cn/livingroom?sub_id=112233"
        parsed = json.loads(handle_tool_call("zju_parse_url", {"url": url}))
        self.assertEqual(parsed["sub_id"], "112233")

    def test_unknown_tool_raises(self):
        with self.assertRaises(ValueError):
            handle_tool_call("zju_not_a_tool", {})

    def test_notifications_get_no_response(self):
        self.assertIsNone(handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_initialize_and_list(self):
        init = handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })
        self.assertEqual(init["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", init["result"]["capabilities"])
        self.assertEqual(init["result"]["serverInfo"]["name"], mcp_server.SERVER_NAME)

        listed = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual(len(listed["result"]["tools"]), len(TOOLS))

    def test_unknown_method_is_rejected(self):
        # resources/list is answered with an empty list so hosts that probe it
        # keep working; a genuinely unknown method must still be rejected.
        resources = handle_request({"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}})
        self.assertEqual(resources["result"]["resources"], [])

        response = handle_request({"jsonrpc": "2.0", "id": 4, "method": "definitely/not/a/method", "params": {}})
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32601)

    def test_transcript_truncation(self):
        text = "x" * 500
        truncated = mcp_server._truncate(text, 100)
        self.assertTrue(truncated.startswith("x" * 100))
        self.assertIn("已截断", truncated)
        self.assertEqual(mcp_server._truncate(text, 1000), text)

    def test_check_note_tool_dispatch(self):
        note = os.path.join(tempfile.gettempdir(), "zju_note_check.md")
        with open(note, "w", encoding="utf-8") as handle:
            handle.write("| A | B |\n| :--- | :--- |\n| $x$ | $|y|=1$ |\n")
        try:
            report = handle_tool_call("zju_check_note", {"file_path": note})
            self.assertIn("不通过", report)
            self.assertIn("table_bare_pipe", report)
        finally:
            if os.path.exists(note):
                os.unlink(note)

    def test_check_note_tool_reports_missing_file(self):
        report = handle_tool_call(
            "zju_check_note", {"file_path": os.path.join(tempfile.gettempdir(), "nope.md")}
        )
        self.assertIn("找不到讲义文件", report)

    def test_check_note_tool_can_fix_in_place(self):
        note = os.path.join(tempfile.gettempdir(), "zju_note_fix.md")
        with open(note, "w", encoding="utf-8") as handle:
            handle.write("| A | B |\n| :--- | :--- |\n| $x$ | $|y|=1$ |\n")
        try:
            report = handle_tool_call("zju_check_note", {"file_path": note, "fix": True})
            self.assertIn("已自动修复", report)
            self.assertIn("结论: 通过", report)
            with open(note, "r", encoding="utf-8") as handle:
                fixed = handle.read()
            self.assertIn("\\lvert y\\rvert", fixed)
        finally:
            if os.path.exists(note):
                os.unlink(note)


class TestCrypto(unittest.TestCase):

    def test_fips197_aes128_known_answer(self):
        """FIPS-197 Appendix C.1: the ported AES-128 decryptor must be correct."""
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        ciphertext = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        expected = bytes.fromhex("00112233445566778899aabbccddeeff")

        round_keys = _key_expansion(key)
        self.assertEqual(_aes128_decrypt_block(ciphertext, round_keys), expected)


class TestEdgeCookie(unittest.TestCase):

    def _make_profile(self, rows=()):
        root = tempfile.mkdtemp(prefix="edge-profile-")
        network = os.path.join(root, "Profile 1", "Network")
        os.makedirs(network)
        db_path = os.path.join(network, "Cookies")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)"
        )
        conn.executemany(
            "INSERT INTO cookies (host_key, name, value, encrypted_value) VALUES (?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()
        return root, db_path

    def test_locked_database_is_reported_as_locked(self):
        root, _db = self._make_profile()
        try:
            with mock.patch("zju_lecture.cookies._edge_root", return_value=root), \
                 mock.patch("zju_lecture.cookies._query_cookie_rows",
                            side_effect=_DirectReadUnavailable("locked")), \
                 mock.patch("zju_lecture.cookies.shutil.copyfile",
                            side_effect=PermissionError(13, "Permission denied")):
                cookie, error = read_edge_cookies("classroom.zju.edu.cn")
            self.assertIsNone(cookie)
            self.assertIsNotNone(error)
            self.assertEqual(error.reason, "locked")
            self.assertIn("Edge", error.hint)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_missing_login_is_reported_as_no_rows(self):
        root, _db = self._make_profile()
        try:
            with mock.patch("zju_lecture.cookies._edge_root", return_value=root):
                cookie, error = read_edge_cookies("classroom.zju.edu.cn")
            self.assertIsNone(cookie)
            self.assertIsNotNone(error)
            self.assertEqual(error.reason, "no_rows")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_host_matching_is_exact_or_subdomain_never_substring(self):
        self.assertTrue(_host_matches("classroom.zju.edu.cn", "classroom.zju.edu.cn"))
        self.assertTrue(_host_matches(".classroom.zju.edu.cn", "classroom.zju.edu.cn"))
        self.assertTrue(_host_matches("a.classroom.zju.edu.cn", "classroom.zju.edu.cn"))
        # A lookalike must never be treated as the classroom host.
        self.assertFalse(_host_matches("classroom.zju.edu.cn.evil.example", "classroom.zju.edu.cn"))
        self.assertFalse(_host_matches("evilclassroom.zju.edu.cn", "classroom.zju.edu.cn"))
        self.assertFalse(_host_matches("other.zju.edu.cn", "classroom.zju.edu.cn"))

    def test_lookalike_host_cookies_are_ignored(self):
        root, _db = self._make_profile(rows=[
            ("classroom.zju.edu.cn.evil.example", "SESSDATA", "lookalike", None),
            ("classroom.zju.edu.cn", "SESSDATA", "real", None),
        ])
        try:
            with mock.patch("zju_lecture.cookies._edge_root", return_value=root):
                cookie, error = read_edge_cookies("classroom.zju.edu.cn")
            self.assertIsNone(error)
            self.assertEqual(cookie, "SESSDATA=real")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_read_cookies_are_normalised(self):
        root, _db = self._make_profile(rows=[
            ("classroom.zju.edu.cn", "SESSION", "token value", None),
        ])
        try:
            with mock.patch("zju_lecture.cookies._edge_root", return_value=root):
                cookie, error = read_edge_cookies("classroom.zju.edu.cn")
            self.assertIsNone(error)
            self.assertEqual(cookie, "SESSION=token value")
            self.assertEqual(sanitize_cookie_header("Cookie: " + cookie), cookie)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestPrivacy(unittest.TestCase):
    """Cookies and personal files must never cross into model-visible output."""

    def setUp(self):
        mcp_server._COOKIE_CACHE.clear()
        REDACTOR.clear()
        for name in ("ZJU_COOKIE", "ZJU_COOKIE_FILE", "ZJU_ALLOW_SENSITIVE_PATHS"):
            os.environ.pop(name, None)

    def tearDown(self):
        mcp_server._COOKIE_CACHE.clear()
        REDACTOR.clear()
        for name in ("ZJU_COOKIE", "ZJU_COOKIE_FILE", "ZJU_ALLOW_SENSITIVE_PATHS"):
            os.environ.pop(name, None)

    def test_redactor_masks_registered_values(self):
        redactor = SecretRedactor()
        redactor.add_cookie("SESSDATA=top-secret-value; acw_tc=another-secret")
        text = redactor.redact("cookie SESSDATA=top-secret-value; acw_tc=another-secret sent")
        self.assertNotIn("top-secret-value", text)
        self.assertNotIn("another-secret", text)
        self.assertIn(REDACTED, text)

    def test_cookie_description_has_no_plaintext(self):
        info = mcp_server.describe_cookie("SESSDATA=top-secret-value; acw_tc=x")
        rendered = json.dumps(info, ensure_ascii=False)
        self.assertNotIn("top-secret-value", rendered)
        self.assertEqual(info["cookie_names"], ["SESSDATA", "acw_tc"])

    def test_mask_cookie_header_hides_values(self):
        self.assertEqual(mask_cookie_header("A=1; B=2"), "A=***; B=***")
        self.assertNotIn("=1", mask_cookie_header("A=1"))

    def test_sanitize_cookie_rejects_header_injection(self):
        with self.assertRaises(ValueError) as caught:
            sanitize_cookie_header("A=1\r\nX-Evil: yes")
        self.assertIn("换行", str(caught.exception))

    def test_env_cookie_is_used_and_registered(self):
        with mock.patch.dict(os.environ, {"ZJU_COOKIE": "SESSDATA=env-secret-value"}), \
             mock.patch("mcp_server.read_edge_cookies") as edge:
            cookie, error, source, reason = mcp_server._resolve_cookie()
        edge.assert_not_called()
        self.assertIsNone(error)
        self.assertIsNone(reason)
        self.assertEqual(cookie, "SESSDATA=env-secret-value")
        self.assertEqual(source, "env")
        self.assertIn(REDACTED, REDACTOR.redact("leak SESSDATA=env-secret-value here"))

    def test_env_cookie_with_newline_is_rejected(self):
        with mock.patch.dict(os.environ, {"ZJU_COOKIE": "A=1\nX-Evil: yes"}):
            cookie, error, _source, reason = mcp_server._resolve_cookie()
        self.assertIsNone(cookie)
        self.assertIn("换行", error or "")
        self.assertNotIn("X-Evil", error or "")
        self.assertEqual(reason, "env_invalid")

    def test_cookie_file_is_used(self):
        path = os.path.join(tempfile.mkdtemp(prefix="zju-cookie-"), "cookie.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("SESSDATA=file-secret-value\n")
        try:
            with mock.patch.dict(os.environ, {"ZJU_COOKIE_FILE": path}):
                cookie, error, source, reason = mcp_server._resolve_cookie()
            self.assertIsNone(error)
            self.assertIsNone(reason)
            self.assertEqual(cookie, "SESSDATA=file-secret-value")
            self.assertEqual(source, "file")
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_read_tool_never_echoes_the_cookie(self):
        mcp_server._COOKIE_CACHE["classroom.zju.edu.cn"] = "SESSDATA=super-secret-value"
        output = handle_tool_call("zju_read_browser_cookie", {})
        self.assertNotIn("super-secret-value", output)
        info = json.loads(output)
        self.assertEqual(info["status"], "success")
        self.assertEqual(info["cookie_names"], ["SESSDATA"])
        self.assertEqual(info["cookie_count"], 1)

    def test_read_tool_has_no_parameters(self):
        tool = next(t for t in TOOLS if t["name"] == "zju_read_browser_cookie")
        self.assertEqual(tool["inputSchema"]["properties"], {})
        self.assertNotIn("required", tool["inputSchema"])

    def test_tool_schemas_expose_no_secret_parameters(self):
        for tool in TOOLS:
            properties = tool["inputSchema"].get("properties", {})
            for forbidden in ("cookie", "reveal", "domain", "token", "password"):
                self.assertNotIn(forbidden, properties, tool["name"])

    def test_tool_errors_are_redacted(self):
        secret = "SESSDATA=super-secret-value"
        mcp_server._COOKIE_CACHE["classroom.zju.edu.cn"] = secret
        REDACTOR.add_cookie(secret)
        with mock.patch(
            "mcp_server.fetch_slides",
            side_effect=mcp_server.ZJUAPIError(f"failed while using {secret}"),
        ):
            response = handle_request({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "zju_fetch_slides", "arguments": {"url_or_sub_id": "123456"}},
            })
        text = response["result"]["content"][0]["text"]
        self.assertNotIn("super-secret-value", text)
        self.assertIn(REDACTED, text)

    def test_courseware_rejects_sensitive_names(self):
        root = tempfile.mkdtemp(prefix="zju-sensitive-")
        try:
            for name in (
                ".env.json",
                "credentials.md",
                "my-secret-notes.md",
                "password.txt",
            ):
                path = os.path.join(root, name)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("PRIVATE=1")
                with self.assertRaises(CoursewareError, msg=name) as caught:
                    extract_courseware_text(path)
                self.assertIn("隐私", str(caught.exception), name)

            normal = os.path.join(root, "lecture-notes.md")
            with open(normal, "w", encoding="utf-8") as handle:
                handle.write("# 线性代数\n")
            self.assertIn("线性代数", extract_courseware_text(normal))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_sensitive_path_escape_hatch_is_explicit(self):
        root = tempfile.mkdtemp(prefix="zju-sensitive-")
        path = os.path.join(root, "credentials.md")
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("courseware text")
            with mock.patch.dict(os.environ, {"ZJU_ALLOW_SENSITIVE_PATHS": "1"}):
                self.assertEqual(guard_local_file(path, {".md"}, kind="课件文件"), os.path.realpath(path))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_guard_rejects_unexpected_extensions(self):
        path = os.path.join(tempfile.mkdtemp(prefix="zju-guard-"), "notes.txt")
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("x")
            with self.assertRaises(Exception):
                guard_local_file(path, {".md"}, kind="讲义文件")
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_check_note_rejects_non_markdown(self):
        path = os.path.join(tempfile.mkdtemp(prefix="zju-note-"), "note.txt")
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("$x$")
            report = handle_tool_call("zju_check_note", {"file_path": path})
            self.assertIn("错误", report)
            self.assertIn("只允许", report)
        finally:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def test_ssl_context_keeps_certificate_verification(self):
        context = create_ssl_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_cross_host_redirect_is_refused(self):
        handler = _SameHostRedirectHandler()
        request = urllib.request.Request("https://classroom.zju.edu.cn/livingroom")
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(
                request, None, 302, "Found", {}, "https://evil.example/steal"
            )

    def test_same_host_redirect_is_allowed(self):
        handler = _SameHostRedirectHandler()
        request = urllib.request.Request("https://classroom.zju.edu.cn/livingroom")
        follow = handler.redirect_request(
            request, None, 302, "Found", {}, "https://classroom.zju.edu.cn/other"
        )
        self.assertIsNotNone(follow)


class TestStdioProtocol(unittest.TestCase):
    """End-to-end check: the server must speak JSON-RPC over stdio."""

    def _rpc(self, process, payload):
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        self.assertTrue(line, "server closed stdout unexpectedly")
        return json.loads(line)

    def test_stdio_round_trip(self):
        process = subprocess.Popen(
            [sys.executable, os.path.join(BASE_DIR, "mcp_server.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", cwd=BASE_DIR,
        )
        try:
            init = self._rpc(process, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "test", "version": "0"}},
            })
            self.assertEqual(init["result"]["serverInfo"]["name"], mcp_server.SERVER_NAME)

            process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            process.stdin.flush()

            listed = self._rpc(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            names = [tool["name"] for tool in listed["result"]["tools"]]
            self.assertIn("zju_fetch_transcript", names)

            called = self._rpc(process, {
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "zju_parse_url",
                           "arguments": {"url": "https://classroom.zju.edu.cn/livingroom?sub_id=112233"}},
            })
            self.assertFalse(called["result"].get("isError"))
            payload = json.loads(called["result"]["content"][0]["text"])
            self.assertEqual(payload["sub_id"], "112233")
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
            process.stdout.close()
            process.stderr.close()


class TransportResilienceTests(unittest.TestCase):
    """回归：单次 TLS/读包抖动不应该让整节课失败。

    线上真实故障序列是：TCP 握手成功 → 读正文时代理截断，抛
    ``IncompleteRead``。旧实现只在"建连"外面包了 try，正文读取发生在重试
    范围之外，所以重试形同虚设。
    """

    def _patch_sleep(self):
        return mock.patch("zju_lecture.client.time.sleep", lambda _seconds: None)

    def test_incomplete_read_is_retried_and_recovers(self):
        import http.client

        from zju_lecture import client as client_module

        class _Response:
            def __init__(self, payload):
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self):
                return self._payload

        calls = {"count": 0}

        def fake_open(url, headers, timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                raise http.client.IncompleteRead(b"\x00" * 16, 200)
            return _Response(b'{"code":0}')

        with self._patch_sleep(), mock.patch.object(client_module, "_open_request", fake_open):
            payload = client_module._fetch_bytes("https://classroom.zju.edu.cn/x", {}, 5)

        self.assertEqual(payload, b'{"code":0}')
        self.assertEqual(calls["count"], 2)

    def test_certificate_failure_is_not_retried(self):
        from zju_lecture import client as client_module

        calls = {"count": 0}

        def fake_open(url, headers, timeout):
            calls["count"] += 1
            raise ssl.SSLCertVerificationError(
                1, "certificate verify failed: unable to get local issuer certificate"
            )

        with self._patch_sleep(), mock.patch.object(client_module, "_open_request", fake_open):
            with self.assertRaises(ssl.SSLCertVerificationError):
                client_module._fetch_bytes("https://classroom.zju.edu.cn/x", {}, 5)

        # 证书问题重试多少次都一样，必须立刻把诊断交出去
        self.assertEqual(calls["count"], 1)

    def test_ssl_error_message_names_cause_and_next_step(self):
        from zju_lecture import client as client_module

        # 真实链路里证书错误总是被 urllib 包一层 URLError，必须能拆包分类
        wrapped = urllib.error.URLError(
            ssl.SSLCertVerificationError(
                1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                   "unable to get local issuer certificate (_ssl.c:1016)"
            )
        )
        message = client_module.describe_network_error(wrapped)
        self.assertIn("证书校验", message)
        self.assertIn("certifi", message)
        self.assertIn("NO_PROXY", message)

    def test_dead_proxy_error_message_points_at_the_proxy(self):
        from zju_lecture import client as client_module

        message = client_module.describe_network_error(
            urllib.error.URLError(ConnectionRefusedError(10061, "由于目标计算机积极拒绝，无法连接。"))
        )
        self.assertIn("代理", message)
        self.assertIn("HTTPS_PROXY", message)

    def test_transcript_error_wraps_actionable_diagnosis(self):
        from zju_lecture import client as client_module

        with mock.patch.object(
            client_module,
            "_fetch_bytes",
            side_effect=urllib.error.URLError(
                ssl.SSLCertVerificationError(1, "certificate verify failed")
            ),
        ):
            with self.assertRaises(client_module.ZJUAPIError) as caught:
                client_module.fetch_transcript("123456")

        text = str(caught.exception)
        self.assertIn("certifi", text)
        self.assertIn("已重试", text)

    def test_fetch_slides_records_reason_instead_of_swallowing_it(self):
        from zju_lecture import client as client_module

        diagnostics = []
        with mock.patch.object(
            client_module,
            "_fetch_bytes",
            side_effect=ssl.SSLCertVerificationError(1, "certificate verify failed"),
        ):
            result = client_module.fetch_slides("123456", cookie="SESSDATA=abc", diagnostics=diagnostics)

        self.assertIsNone(result)
        self.assertEqual(len(diagnostics), 1)
        # 以前这里是 except Exception: pass —— 调用方只能猜"是不是没登录"
        self.assertIn("certifi", diagnostics[0])

    def test_fetch_slides_without_cookie_records_that_reason(self):
        from zju_lecture import client as client_module

        diagnostics = []
        self.assertIsNone(client_module.fetch_slides("123456", diagnostics=diagnostics))
        self.assertEqual(diagnostics, ["未提供登录 Cookie"])


class TrustStoreTests(unittest.TestCase):
    """随包 CA 兜底：dsh 自带 Python 没有 certifi，系统根证书又可能不全。"""

    def tearDown(self):
        from zju_lecture import client as client_module

        # 每个用例都会重建 context，别把状态漏给后面的用例
        client_module._SSL_CONTEXT = None
        client_module.create_ssl_context()

    def test_bundled_bundle_ships_and_parses(self):
        from zju_lecture import client as client_module

        path = client_module._bundled_ca_path()
        self.assertIsNotNone(path, "插件必须随包携带 cacert.pem")
        with open(path, "rb") as handle:
            data = handle.read()
        self.assertGreater(len(data), 50_000)
        self.assertIn(b"-----BEGIN CERTIFICATE-----", data)
        self.assertGreaterEqual(data.count(b"-----BEGIN CERTIFICATE-----"), 50)

    def test_bundled_bundle_is_a_usable_trust_store(self):
        from zju_lecture import client as client_module

        context = client_module._context_from_cafile(client_module._bundled_ca_path())
        self.assertIsNotNone(context)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreater(len(context.get_ca_certs()), 50)

    def test_bundled_bundle_is_used_when_certifi_is_absent(self):
        from zju_lecture import client as client_module

        with mock.patch.object(client_module, "_certifi_ca_path", lambda: None):
            context = client_module.create_ssl_context()

        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(client_module._CA_SOURCE, "bundled")
        self.assertGreater(len(context.get_ca_certs()), 50)

    def test_certifi_wins_over_the_bundled_bundle(self):
        from zju_lecture import client as client_module

        bundled = client_module._bundled_ca_path()
        with mock.patch.object(client_module, "_certifi_ca_path", lambda: bundled):
            client_module.create_ssl_context()

        self.assertEqual(client_module._CA_SOURCE, "certifi")

    def test_system_store_is_the_last_resort(self):
        from zju_lecture import client as client_module

        with mock.patch.object(client_module, "_certifi_ca_path", lambda: None), mock.patch.object(
            client_module, "_bundled_ca_path", lambda: None
        ):
            context = client_module.create_ssl_context()

        self.assertEqual(client_module._CA_SOURCE, "system")
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_health_reports_which_store_is_live(self):
        from zju_lecture import client as client_module

        health = client_module.ssl_context_health()
        self.assertIn(health["source"], {"certifi", "bundled", "system"})
        self.assertIsInstance(health["ca_certs"], int)

    def test_certificate_message_names_the_live_store(self):
        from zju_lecture import client as client_module

        message = client_module.describe_network_error(
            ssl.SSLCertVerificationError(1, "certificate verify failed")
        )
        self.assertIn("信任库：", message)
        self.assertIn(str(client_module.ssl_context_health()["ca_certs"]), message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
