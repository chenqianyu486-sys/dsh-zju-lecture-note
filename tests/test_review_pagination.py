"""Review 09: every page advances and the transcript can be reconstructed."""
import json
import unittest
from unittest import mock

import mcp_server
from zju_lecture.formatter import build_transcript_views


class TestTranscriptPagination(unittest.TestCase):
    def paginate(self, segments, view, budget=1000):
        cursor = ""
        seen = set()
        output = []
        with mock.patch.object(mcp_server, "fetch_transcript", return_value=segments):
            for _ in range(200):
                args = {"url_or_sub_id": "123456", "view_format": view, "max_chars": budget}
                if cursor:
                    args["cursor"] = cursor
                text = mcp_server.handle_tool_call("zju_fetch_transcript", args)
                self.assertLessEqual(len(text), budget)
                payload = json.loads(text)
                records = payload["chunks" if view == "chunked" else "segments"]
                self.assertTrue(records, "nonempty input must yield content")
                self.assertTrue(any(r["text"] for r in records))
                output.extend(records)
                if not payload["truncated"]:
                    self.assertIsNone(payload.get("next_cursor"))
                    return output
                cursor = payload.get("next_cursor")
                self.assertTrue(cursor, "truncation needs an exact continuation cursor")
                self.assertNotIn(cursor, seen, "cursor did not advance")
                seen.add(cursor)
        self.fail("pagination did not finish")

    def test_json_recovers_all_segments_from_one_minute(self):
        segments = [{"begin_sec": i * 3, "text": "S%02d:" % i + "教学内容。" * 15} for i in range(20)]
        result = self.paginate(segments, "json")
        self.assertEqual("".join(s["text"] for s in result), "".join(s["text"] for s in segments))

    def test_single_long_segment_is_split_without_loss(self):
        text = "长字幕\\\"\n" * 700 + "END_SENTINEL"
        result = self.paginate([{"begin_sec": 0, "text": text}], "json")
        self.assertEqual("".join(s["text"] for s in result), text)

    def test_chunked_minute_larger_than_budget_is_split_without_loss(self):
        segments = [{"begin_sec": 0, "text": "长字幕。" * 900 + "END_SENTINEL"}]
        result = self.paginate(segments, "chunked")
        self.assertEqual("".join(s["text"] for s in result), build_transcript_views(segments)[1])

    def test_chunks_reconstruct_all_minute_boundaries(self):
        segments = [{"begin_sec": i * 60, "text": str(i) + "文本。" * 150} for i in range(30)]
        result = self.paginate(segments, "chunked", 1800)
        chunks = {}
        for item in result:
            chunks[item["chunk_index"]] = chunks.get(item["chunk_index"], "") + item["text"]
        self.assertEqual("\n".join(chunks.values()), build_transcript_views(segments)[1])

    def test_invalid_cursor_is_reported_without_silently_restarting(self):
        with mock.patch.object(mcp_server, "fetch_transcript", return_value=[{"begin_sec": 0, "text": "abc"}]):
            for cursor in ("bad", "s:-1:0", "s:99:0", "s:0:999"):
                with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                    mcp_server.handle_tool_call("zju_fetch_transcript", {
                        "url_or_sub_id": "123456", "view_format": "json", "cursor": cursor,
                    })

    def test_zero_offset_can_resume_at_an_empty_record(self):
        segments = [
            {"begin_sec": 0, "text": "x" * 708},
            {"begin_sec": 1, "text": ""},
            {"begin_sec": 2, "text": "tail" * 100},
        ]
        first = json.loads(mcp_server._segments_payload("123456", segments, "00:01", 1000))
        self.assertEqual(first["next_cursor"], "s:1:0")
        second = json.loads(mcp_server._segments_payload(
            "123456", segments, "00:01", 1000, cursor=first["next_cursor"],
        ))
        self.assertFalse(second["truncated"])
        self.assertEqual(first["segments"] + second["segments"], segments)


if __name__ == "__main__":
    unittest.main()
