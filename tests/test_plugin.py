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
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from zju_lecture.client import parse_lecture_url
from zju_lecture.cookies import _aes128_decrypt_block, _key_expansion, read_edge_cookies
from zju_lecture.formatter import (
    build_transcript_views,
    chunk_transcript,
    filter_segments,
    format_minute_span,
    format_timestamp,
)
from zju_lecture.courseware import extract_courseware_text
from zju_lecture.note_lint import check_markdown, fix_markdown
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
