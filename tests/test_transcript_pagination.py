"""#09 回归：json/chunked 长字幕无损分页，游标精确续取且绑定课程。

旧实现 json 视图对超长单条硬截断 JSON（非法/零进度），chunked 切单条后
next_start_minute 跳到下一块丢掉剩余，且 chunk 边界随 max_chars 变。这里验证
游标续取可完整重建原文、改预算仍稳定、游标绑定课程与视图、绝不返回半截 JSON。
"""

import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import mcp_server  # noqa: E402
from zju_lecture.formatter import build_transcript_views  # noqa: E402


class TestTranscriptPagination(unittest.TestCase):
    def paginate(self, segments, view, budget=1000, sub_id="123456"):
        cursor = ""
        seen = set()
        output = []
        with mock.patch.object(mcp_server, "fetch_transcript", return_value=segments):
            for _ in range(500):
                args = {"url_or_sub_id": sub_id, "view_format": view, "max_chars": budget}
                if cursor:
                    args["cursor"] = cursor
                text = mcp_server.handle_tool_call("zju_fetch_transcript", args)
                self.assertLessEqual(len(text), budget)
                payload = json.loads(text)
                records = payload["chunks" if view == "chunked" else "segments"]
                self.assertTrue(records, "nonempty input must yield content")
                output.extend(records)
                if not payload["truncated"]:
                    self.assertIsNone(payload.get("next_cursor"))
                    return output
                cursor = payload.get("next_cursor")
                self.assertTrue(cursor, "truncation needs an exact continuation cursor")
                self.assertNotIn(cursor, seen, "cursor did not advance")
                seen.add(cursor)
        self.fail("pagination did not finish")

    def test_json_recovers_all_segments(self):
        segments = [{"begin_sec": i * 3, "text": "S%02d:" % i + "教学内容。" * 15} for i in range(20)]
        result = self.paginate(segments, "json")
        self.assertEqual("".join(s["text"] for s in result), "".join(s["text"] for s in segments))

    def test_single_long_segment_split_without_loss(self):
        text = "长字幕\\\"\n" * 700 + "END_SENTINEL"
        result = self.paginate([{"begin_sec": 0, "text": text}], "json")
        self.assertEqual("".join(s["text"] for s in result), text)

    def test_chunked_minute_larger_than_budget_split_without_loss(self):
        segments = [{"begin_sec": 0, "text": "长字幕。" * 900 + "END_SENTINEL"}]
        result = self.paginate(segments, "chunked")
        self.assertEqual("".join(s["text"] for s in result), build_transcript_views(segments)[1])

    def test_budget_change_midstream_still_lossless(self):
        segments = [{"begin_sec": i * 60, "text": str(i) + "文本。" * 150} for i in range(30)]
        budgets = [1800, 2500, 1500, 3000]
        cursor = ""
        chunks = {}
        with mock.patch.object(mcp_server, "fetch_transcript", return_value=segments):
            for i in range(500):
                args = {
                    "url_or_sub_id": "123456", "view_format": "chunked",
                    "max_chars": budgets[i % len(budgets)],
                }
                if cursor:
                    args["cursor"] = cursor
                payload = json.loads(mcp_server.handle_tool_call("zju_fetch_transcript", args))
                for item in payload["chunks"]:
                    chunks[item["chunk_index"]] = chunks.get(item["chunk_index"], "") + item["text"]
                if not payload["truncated"]:
                    break
                cursor = payload["next_cursor"]
        self.assertEqual("\n".join(chunks.values()), build_transcript_views(segments)[1])

    def test_zero_offset_can_resume_at_an_empty_record(self):
        segments = [
            {"begin_sec": 0, "text": "x" * 708},
            {"begin_sec": 1, "text": ""},
            {"begin_sec": 2, "text": "tail" * 100},
        ]
        first = json.loads(mcp_server._segments_payload("123456", segments, "00:01", 1000))
        self.assertEqual(first["next_cursor"].split(":")[2], "1")
        second = json.loads(mcp_server._segments_payload(
            "123456", segments, "00:01", 1000, cursor=first["next_cursor"]
        ))
        self.assertFalse(second["truncated"])
        self.assertEqual(first["segments"] + second["segments"], segments)

    def test_invalid_cursor_rejected(self):
        with mock.patch.object(mcp_server, "fetch_transcript", return_value=[{"begin_sec": 0, "text": "abc"}]):
            for cursor in ("bad", "s:-1:0", "s:99:0", "s:0:999", "c:0:0"):
                with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                    mcp_server.handle_tool_call("zju_fetch_transcript", {
                        "url_or_sub_id": "123456", "view_format": "json", "cursor": cursor,
                    })

    def test_cursor_bound_to_sub_id(self):
        segments = [{"begin_sec": i * 3, "text": "内容。" * 50} for i in range(10)]
        with mock.patch.object(mcp_server, "fetch_transcript", return_value=segments):
            first = json.loads(mcp_server.handle_tool_call("zju_fetch_transcript", {
                "url_or_sub_id": "123456", "view_format": "json", "max_chars": 1000,
            }))
            cursor = first["next_cursor"]
            with self.assertRaises(ValueError):
                mcp_server.handle_tool_call("zju_fetch_transcript", {
                    "url_or_sub_id": "999999", "view_format": "json", "max_chars": 1000, "cursor": cursor,
                })

    def test_cursor_rejected_for_text_views(self):
        with mock.patch.object(mcp_server, "fetch_transcript", return_value=[{"begin_sec": 0, "text": "abc"}]):
            with self.assertRaises(ValueError):
                mcp_server.handle_tool_call("zju_fetch_transcript", {
                    "url_or_sub_id": "123456", "view_format": "per_minute", "cursor": "s:0:0",
                })


if __name__ == "__main__":
    unittest.main()