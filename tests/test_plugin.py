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
