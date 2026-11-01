# -*- coding: utf-8 -*-
"""Tests for the v1.5.0 slide pipeline: auth, pagination, downloads, PDF."""

import base64
import io
import json
import os
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import zlib
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zju_lecture import client as client_module
from zju_lecture import cookies as cookies_module
from zju_lecture import slides as slides_module
from zju_lecture.formatter import format_slides_as_markdown
from zju_lecture.paths import artifact_dir

# 1x1 grayscale JPEG, enough for the header parser and the PDF writer.
TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
    "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=="
)


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def _png_rgb(width: int, height: int, rows):
    raw = b"".join(b"\x00" + bytes(row) for row in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


def _token_cookie(token: str = "tok-123") -> str:
    payload = '{i:0;s:6:"_token";i:0;s:%d:"%s";}' % (len(token), token)
    return "SESSION=" + urllib.parse.quote(payload) + "; OTHER=1"


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


class TestClassroomToken(unittest.TestCase):
    def test_php_serialized_token_is_extracted(self):
        self.assertEqual(client_module.extract_classroom_token(_token_cookie()), "tok-123")

    def test_plain_token_cookie_is_accepted(self):
        self.assertEqual(
            client_module.extract_classroom_token("A=1; _token=plain-token; B=2"),
            "plain-token",
        )

    def test_missing_token_returns_none(self):
        self.assertIsNone(client_module.extract_classroom_token("SESSION=abc; X=1"))
        self.assertIsNone(client_module.extract_classroom_token(""))

    def test_control_characters_are_rejected(self):
        self.assertIsNone(
            client_module.extract_classroom_token("_token=abc\r\nInjected: yes")
        )

    def test_zju_url_is_upgraded_to_https(self):
        self.assertEqual(
            client_module.secure_zju_url("http://media.cmc.zju.edu.cn/a.jpg"),
            "https://media.cmc.zju.edu.cn/a.jpg",
        )
        self.assertEqual(
            client_module.secure_zju_url("http://example.com/a.jpg"),
            "http://example.com/a.jpg",
        )
        self.assertTrue(client_module.is_zju_host("a.b.zju.edu.cn"))
        self.assertFalse(client_module.is_zju_host("zju.edu.cn.evil.example"))

    def test_token_is_registered_with_the_redactor(self):
        import mcp_server

        mcp_server._COOKIE_CACHE.clear()
        mcp_server.REDACTOR.clear()
        self.addCleanup(mcp_server._COOKIE_CACHE.clear)
        self.addCleanup(mcp_server.REDACTOR.clear)
        mcp_server._remember_cookie(_token_cookie("tok-secret-123"))
        self.assertEqual(
            mcp_server.REDACTOR.redact("value=tok-secret-123"),
            "value=[REDACTED]",
        )


class TestNormalizeSlide(unittest.TestCase):
    def test_content_json_string_is_unpacked(self):
        slide = client_module.normalize_slide(
            {"content": json.dumps({"pptimgurl": "http://media.cmc.zju.edu.cn/a.jpg"})},
            3,
        )
        self.assertEqual(slide["page"], 3)
        self.assertEqual(slide["image_url"], "https://media.cmc.zju.edu.cn/a.jpg")
        self.assertEqual(slide["text"], "")

    def test_text_and_timestamp_are_kept(self):
        slide = client_module.normalize_slide(
            {"content": json.dumps({"ocr_content": "傅里叶变换", "time": 125})},
            1,
        )
        self.assertEqual(slide["text"], "傅里叶变换")
        self.assertEqual(slide["time"], 125)

    def test_plain_text_content_is_not_treated_as_json(self):
        slide = client_module.normalize_slide({"content": "手写内容"}, 1)
        self.assertEqual(slide["text"], "手写内容")
        self.assertEqual(slide["image_url"], "")


class TestFetchSlides(unittest.TestCase):
    def _fake_fetch(self, pages, calls):
        def fake_fetch(url, headers, timeout, **kwargs):
            calls.append((url, dict(headers)))
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            page = int(query["page"][0])
            return json.dumps(pages[page]).encode("utf-8")

        return fake_fetch

    def test_pagination_dedupes_and_sends_bearer(self):
        page_one = {
            "code": 0,
            "total": 3,
            "list": [
                {"content": json.dumps({"pptimgurl": "http://media.cmc.zju.edu.cn/1.jpg"})},
                {"content": json.dumps({"pptimgurl": "https://media.cmc.zju.edu.cn/2.jpg"})},
            ],
        }
        page_two = {
            "code": 0,
            "total": 3,
            "list": [
                {"content": json.dumps({"pptimgurl": "https://media.cmc.zju.edu.cn/2.jpg"})},
                {"content": json.dumps({"pptimgurl": "https://media.cmc.zju.edu.cn/3.jpg"})},
            ],
        }
        calls = []
        diagnostics = []
        with mock.patch.object(
            client_module, "_fetch_bytes", self._fake_fetch({1: page_one, 2: page_two}, calls)
        ):
            slides = client_module.fetch_slides(
                "123456",
                cookie=_token_cookie(),
                course_id="58133",
                diagnostics=diagnostics,
            )

        self.assertEqual([slide["image_url"] for slide in slides], [
            "https://media.cmc.zju.edu.cn/1.jpg",
            "https://media.cmc.zju.edu.cn/2.jpg",
            "https://media.cmc.zju.edu.cn/3.jpg",
        ])
        self.assertEqual(len(calls), 2)
        self.assertIn("course_id=58133", calls[0][0])
        self.assertIn("page=1", calls[0][0])
        self.assertIn("per_page=100", calls[0][0])
        self.assertEqual(calls[0][1]["Authorization"], "Bearer tok-123")
        self.assertEqual(diagnostics, [])

    def test_repeated_page_stops_without_duplicates(self):
        page = {
            "code": 0,
            "total": 100,
            "list": [
                {"content": json.dumps({"pptimgurl": "https://media.cmc.zju.edu.cn/1.jpg"})},
            ],
        }
        calls = []
        diagnostics = []
        with mock.patch.object(
            client_module, "_fetch_bytes", self._fake_fetch({1: page, 2: page}, calls)
        ):
            slides = client_module.fetch_slides(
                "123456", cookie=_token_cookie(), course_id="58133", diagnostics=diagnostics
            )
        self.assertEqual(len(slides), 1)
        self.assertEqual(len(calls), 2)
        self.assertTrue(any("只取到 1" in item or "1 张" in item for item in diagnostics))

    def test_http_401_names_the_login_problem(self):
        def fake_fetch(url, headers, timeout, **kwargs):
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b""))

        diagnostics = []
        with mock.patch.object(client_module, "_fetch_bytes", fake_fetch):
            result = client_module.fetch_slides(
                "123456", cookie="SESSION=no-token", course_id="58133", diagnostics=diagnostics
            )
        self.assertIsNone(result)
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("401", diagnostics[0])
        self.assertIn("重新登录", diagnostics[0])

    def test_empty_list_without_course_id_asks_for_it(self):
        def fake_fetch(url, headers, timeout, **kwargs):
            return b'{"code":0,"total":0,"list":[]}'

        diagnostics = []
        with mock.patch.object(client_module, "_fetch_bytes", fake_fetch):
            result = client_module.fetch_slides(
                "123456", cookie=_token_cookie(), diagnostics=diagnostics
            )
        self.assertIsNone(result)
        self.assertTrue(any("course_id" in item for item in diagnostics))


class TestParentDomainCookies(unittest.TestCase):
    def _profile(self, rows):
        root = tempfile.mkdtemp(prefix="edge-profile-")
        network = os.path.join(root, "Profile 1", "Network")
        os.makedirs(network)
        connection = sqlite3.connect(os.path.join(network, "Cookies"))
        connection.execute(
            "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)"
        )
        connection.executemany(
            "INSERT INTO cookies VALUES (?,?,?,?)",
            rows,
        )
        connection.commit()
        connection.close()
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def test_parent_domain_token_is_included_but_other_subdomains_are_not(self):
        root = self._profile([
            ("classroom.zju.edu.cn", "CLASS", "c1", None),
            (".zju.edu.cn", "SESSION", "parent-token", None),
            ("courses.zju.edu.cn", "COURSE", "must-not-leak", None),
            (".courses.zju.edu.cn", "COURSE2", "must-not-leak", None),
        ])
        with mock.patch.object(cookies_module, "_edge_root", return_value=root):
            cookie, error = cookies_module.read_edge_cookies("classroom.zju.edu.cn")
        self.assertIsNone(error)
        self.assertEqual(cookie, "CLASS=c1; SESSION=parent-token")

    def test_classroom_cookie_wins_on_name_collision(self):
        root = self._profile([
            (".zju.edu.cn", "SESSION", "parent-token", None),
            ("classroom.zju.edu.cn", "SESSION", "classroom-token", None),
        ])
        with mock.patch.object(cookies_module, "_edge_root", return_value=root):
            cookie, error = cookies_module.read_edge_cookies("classroom.zju.edu.cn")
        self.assertIsNone(error)
        self.assertEqual(cookie, "SESSION=classroom-token")

    def test_parent_domain_derivation(self):
        self.assertEqual(
            cookies_module._parent_domain("classroom.zju.edu.cn"), "zju.edu.cn"
        )
        self.assertEqual(
            cookies_module._parent_domain("a.b.zju.edu.cn"), "zju.edu.cn"
        )
        self.assertIsNone(cookies_module._parent_domain("zju.edu.cn"))


class TestDownloadAndPdf(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="zju-slides-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_download_dedupes_consecutive_identical_images(self):
        slides = [
            {"page": 1, "image_url": "https://media.cmc.zju.edu.cn/1.jpg", "text": ""},
            {"page": 2, "image_url": "https://media.cmc.zju.edu.cn/2.jpg", "text": ""},
            {"page": 3, "image_url": "https://media.cmc.zju.edu.cn/3.png", "text": ""},
        ]
        png = _png_rgb(2, 2, [[255, 0, 0, 0, 255, 0], [0, 0, 255, 255, 255, 255]])
        payloads = {
            "https://media.cmc.zju.edu.cn/1.jpg": TINY_JPEG,
            "https://media.cmc.zju.edu.cn/2.jpg": TINY_JPEG,
            "https://media.cmc.zju.edu.cn/3.png": png,
        }
        seen_headers = []

        def fake_fetch(url, headers, timeout, **kwargs):
            seen_headers.append(dict(headers))
            return payloads[url]

        with mock.patch.object(slides_module, "_fetch_bytes", fake_fetch):
            summary = slides_module.download_slides(
                slides,
                os.path.join(self.dir, "images"),
                cookie="SESSION=secret",
                sub_id="123456",
                dedup=True,
            )

        self.assertEqual(summary["downloaded"], 3)
        self.assertEqual(summary["duplicates"], 1)
        self.assertEqual(len(summary["pages"]), 2)
        self.assertEqual(slides[0]["sha256"], slides[1]["sha256"])
        self.assertTrue(os.path.isfile(slides[0]["local_path"]))
        self.assertTrue(os.path.isfile(slides[2]["local_path"]))
        # Cookie is sent to a ZJU image host, but never Authorization.
        self.assertEqual(seen_headers[0]["Cookie"], "SESSION=secret")
        self.assertNotIn("Authorization", seen_headers[0])

        pdf_path = os.path.join(self.dir, "deck.pdf")
        written = slides_module.build_slides_pdf(summary["pages"], pdf_path)
        self.assertEqual(written, pdf_path)
        data = _read_bytes(pdf_path)
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertTrue(data.rstrip().endswith(b"%%EOF"))
        self.assertEqual(len(re.findall(rb"/Type /Page(?!s)", data)), 2)
        self.assertIn(b"/DCTDecode", data)
        self.assertIn(b"/FlateDecode", data)

    def test_non_zju_image_url_is_refused(self):
        slides = [{"page": 1, "image_url": "https://evil.example/a.jpg", "text": ""}]
        calls = []

        def fake_fetch(url, headers, timeout, **kwargs):
            calls.append(url)
            return TINY_JPEG

        diagnostics = []
        with mock.patch.object(slides_module, "_fetch_bytes", fake_fetch):
            summary = slides_module.download_slides(
                slides, os.path.join(self.dir, "images"), diagnostics=diagnostics
            )
        self.assertEqual(summary["downloaded"], 0)
        self.assertEqual(calls, [])
        self.assertTrue(any("浙大主机" in item for item in diagnostics))

    def test_403_retries_with_bearer(self):
        slides = [{"page": 1, "image_url": "https://media.cmc.zju.edu.cn/1.jpg", "text": ""}]
        seen_auth = []

        def fake_fetch(url, headers, timeout, **kwargs):
            seen_auth.append(headers.get("Authorization"))
            if headers.get("Authorization") is None:
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b""))
            return TINY_JPEG

        with mock.patch.object(slides_module, "_fetch_bytes", fake_fetch):
            summary = slides_module.download_slides(
                slides,
                os.path.join(self.dir, "images"),
                cookie=_token_cookie("tok-abc"),
            )
        self.assertEqual(summary["downloaded"], 1)
        self.assertEqual(seen_auth, [None, "Bearer tok-abc"])

    def test_pdf_writer_handles_jpeg_and_png(self):
        jpeg_path = os.path.join(self.dir, "a.jpg")
        png_path = os.path.join(self.dir, "b.png")
        with open(jpeg_path, "wb") as handle:
            handle.write(TINY_JPEG)
        with open(png_path, "wb") as handle:
            handle.write(_png_rgb(2, 2, [[255, 0, 0, 0, 255, 0], [0, 0, 255, 255, 255, 255]]))
        pdf_path = os.path.join(self.dir, "deck.pdf")
        self.assertEqual(
            slides_module.build_slides_pdf([jpeg_path, png_path], pdf_path),
            pdf_path,
        )
        data = _read_bytes(pdf_path)
        self.assertIn(b"/Count 2", data)
        self.assertEqual(data.count(b"/Subtype /Image"), 2)
        self.assertIn(b"/DCTDecode", data)
        self.assertIn(b"/FlateDecode", data)

    def test_png_filters_are_reversed(self):
        rows = [
            [10, 20, 30],
            [12, 18, 33],
            [15, 15, 40],
        ]
        encoded_rows = []
        previous = [0, 0, 0]
        for index, row in enumerate(rows):
            filter_type = index + 1
            encoded = []
            for column, value in enumerate(row):
                left = row[column - 3] if column >= 3 else 0
                up = previous[column]
                up_left = previous[column - 3] if column >= 3 else 0
                if filter_type == 1:
                    predictor = left
                elif filter_type == 2:
                    predictor = up
                elif filter_type == 3:
                    predictor = (left + up) >> 1
                else:
                    predictor = slides_module._paeth(left, up, up_left)
                encoded.append((value - predictor) & 0xFF)
            encoded_rows.append(bytes(encoded))
            previous = row

        raw = b"".join(
            bytes([index + 1]) + encoded
            for index, encoded in enumerate(encoded_rows)
        )
        ihdr = struct.pack(">IIBBBBB", 1, 3, 8, 2, 0, 0, 0)
        png = (
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(raw))
            + _png_chunk(b"IEND", b"")
        )
        width, height, samples, channels = slides_module._png_decode(png)
        self.assertEqual((width, height, channels), (1, 3, 3))
        self.assertEqual(samples, bytes(value for row in rows for value in row))


class TestArtifactDir(unittest.TestCase):
    def test_relative_directory_stays_in_workspace(self):
        workspace = tempfile.mkdtemp(prefix="zju-workspace-")
        self.addCleanup(shutil.rmtree, workspace, True)
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": workspace, "PWD": workspace}):
            target, error = artifact_dir("ppt-assets/123456")
        self.assertIsNone(error)
        self.assertEqual(
            os.path.normcase(target),
            os.path.normcase(os.path.join(workspace, "ppt-assets", "123456")),
        )
        self.assertTrue(os.path.isdir(target))

    def test_escape_is_refused(self):
        workspace = tempfile.mkdtemp(prefix="zju-workspace-")
        self.addCleanup(shutil.rmtree, workspace, True)
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": workspace, "PWD": workspace}):
            target, error = artifact_dir("../outside")
        self.assertIsNone(target)
        self.assertIn("工作区之外", error or "")


class TestSlideFormatter(unittest.TestCase):
    def test_local_file_replaces_remote_url(self):
        slides = [{
            "page": 1,
            "image_url": "https://media.cmc.zju.edu.cn/1.jpg",
            "local_path": "/tmp/slide-0001.jpg",
            "text": "",
        }]
        text = format_slides_as_markdown(slides, pdf_path="/tmp/deck.pdf")
        self.assertIn("完整 PDF: /tmp/deck.pdf", text)
        self.assertIn("截图文件: /tmp/slide-0001.jpg", text)
        self.assertNotIn("https://media.cmc.zju.edu.cn/1.jpg", text)

    def test_remote_url_is_shown_when_not_downloaded(self):
        text = format_slides_as_markdown([{
            "page": 2,
            "image_url": "https://media.cmc.zju.edu.cn/2.jpg",
            "text": "极限的定义",
        }])
        self.assertIn("第 2 页", text)
        self.assertIn("极限的定义", text)
        self.assertIn("截图: https://media.cmc.zju.edu.cn/2.jpg", text)
        self.assertNotIn("OCR", text)


class TestToolSchema(unittest.TestCase):
    def test_slide_tool_exposes_download_controls(self):
        import mcp_server

        tool = next(item for item in mcp_server.TOOLS if item["name"] == "zju_fetch_slides")
        properties = tool["inputSchema"]["properties"]
        for name in ("course_id", "download", "output_dir", "dedup"):
            self.assertIn(name, properties)
        self.assertNotIn("文字层与 OCR", tool["description"])


class TestMcpHandler(unittest.TestCase):
    def test_download_reports_pdf_and_local_files(self):
        import mcp_server

        slides = [{
            "page": 1,
            "image_url": "https://media.cmc.zju.edu.cn/1.jpg",
            "text": "",
            "local_path": "/tmp/slide-0001.jpg",
        }]
        summary = {
            "downloaded": 1,
            "failed": 0,
            "skipped": 0,
            "duplicates": 0,
            "images_dir": "/tmp/images",
            "pages": slides,
            "total_bytes": 10,
        }
        with mock.patch.object(
            mcp_server, "_resolve_cookie", return_value=("S=1", None, "cache", None)
        ), mock.patch.object(mcp_server, "fetch_slides", return_value=slides), \
                mock.patch.object(mcp_server, "artifact_dir", return_value=("/tmp/ppt", None)), \
                mock.patch.object(mcp_server, "download_slides", return_value=summary), \
                mock.patch.object(
                    mcp_server, "build_slides_pdf", return_value="/tmp/ppt/PPT-123.pdf"
                ):
            output = mcp_server.handle_tool_call("zju_fetch_slides", {
                "url_or_sub_id": (
                    "https://classroom.zju.edu.cn/livingroom?course_id=1&sub_id=123"
                ),
                "download": True,
            })
        self.assertIn("PDF: /tmp/ppt/PPT-123.pdf", output)
        self.assertIn("截图文件: /tmp/slide-0001.jpg", output)
        self.assertIn("不是文字层", output)

    def test_metadata_only_shows_remote_url(self):
        import mcp_server

        slides = [{
            "page": 2,
            "image_url": "https://media.cmc.zju.edu.cn/2.jpg",
            "text": "",
        }]
        with mock.patch.object(
            mcp_server, "_resolve_cookie", return_value=("S=1", None, "cache", None)
        ), mock.patch.object(mcp_server, "fetch_slides", return_value=slides):
            output = mcp_server.handle_tool_call("zju_fetch_slides", {
                "url_or_sub_id": (
                    "https://classroom.zju.edu.cn/livingroom?course_id=1&sub_id=123"
                ),
            })
        self.assertIn("截图: https://media.cmc.zju.edu.cn/2.jpg", output)
        self.assertNotIn("PDF:", output)


if __name__ == "__main__":
    unittest.main()
