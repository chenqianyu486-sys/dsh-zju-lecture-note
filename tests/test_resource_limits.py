#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资源上限（安全审查 P1-4 / 7.9）。

四类输入以前没有硬上限：PPTX/DOCX 整成员读取、PNG 先完整解压再检查、
截图总量只告警不停止、Typst 下载没有字节上限。恶意课件 / 图片 / 镜像
可以把内存、磁盘或网络打满。

现在：课件按 ZipInfo.file_size 预检（单成员 16 MiB / 合计 64 MiB）；
PNG 用 decompressobj 限制输出；截图达到总量上限即停止后续下载；
Typst 下载超过 256 MiB 中断并删除半成品；tar 拒绝链接成员。
"""

import io
import os
import shutil
import struct
import sys
import tarfile
import tempfile
import unittest
import zipfile
import zlib
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zju_lecture import courseware, deps, slides  # noqa: E402


def _png_chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def make_png(width, height, color_type=2, raw_override=None):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    if raw_override is None:
        channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
        raw_override = b"\x00" * (height * (width * channels + 1))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw_override))
        + _png_chunk(b"IEND", b"")
    )


class TestArchiveLimits(unittest.TestCase):

    def test_limits_are_the_documented_values(self):
        self.assertEqual(courseware.MAX_ARCHIVE_TOTAL_BYTES, 64 * 1024 * 1024)
        self.assertEqual(courseware.MAX_ARCHIVE_MEMBER_BYTES, 16 * 1024 * 1024)

    def _docx(self, directory, payload):
        path = os.path.join(directory, "课件.docx")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", payload)
        return path

    def test_high_ratio_member_is_rejected_before_extraction(self):
        directory = tempfile.mkdtemp(prefix="zju-zip-")
        try:
            # 8 MiB 的零压缩后只有几 KB：磁盘上很小，解压后很大。
            path = self._docx(directory, b"<w:t>" + b"\x00" * (8 * 1024 * 1024) + b"</w:t>")
            with mock.patch.object(courseware, "MAX_ARCHIVE_MEMBER_BYTES", 1024 * 1024), \
                    mock.patch.object(courseware, "MAX_ARCHIVE_TOTAL_BYTES", 4 * 1024 * 1024):
                with self.assertRaises(courseware.CoursewareError) as caught:
                    courseware.extract_courseware_text(path)
            self.assertIn("MiB", str(caught.exception))
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_total_size_limit_is_enforced_across_members(self):
        directory = tempfile.mkdtemp(prefix="zju-zip-")
        try:
            path = os.path.join(directory, "课件.docx")
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("word/document.xml", b"a" * 600)
                archive.writestr("word/other.xml", b"b" * 600)
            with mock.patch.object(courseware, "MAX_ARCHIVE_MEMBER_BYTES", 1024 * 1024), \
                    mock.patch.object(courseware, "MAX_ARCHIVE_TOTAL_BYTES", 1000):
                with self.assertRaises(courseware.CoursewareError):
                    courseware.extract_courseware_text(path)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_normal_docx_still_extracts(self):
        directory = tempfile.mkdtemp(prefix="zju-zip-")
        try:
            path = self._docx(directory, "<w:p><w:t>线性代数</w:t></w:p>")
            self.assertIn("线性代数", courseware.extract_courseware_text(path))
        finally:
            shutil.rmtree(directory, ignore_errors=True)


class TestPngLimit(unittest.TestCase):

    def test_oversized_decompressed_stream_is_rejected(self):
        # 声明的像素数据只要 ~30 KB，IDAT 却解压出 200 KB。
        bomb = make_png(100, 100, raw_override=b"\x00" * 200000)
        with self.assertRaises(slides.SlideError) as caught:
            slides._png_decode(bomb)
        self.assertIn("超过", str(caught.exception))

    def test_valid_png_still_decodes(self):
        width, height, samples, channels = slides._png_decode(make_png(4, 3))
        self.assertEqual((width, height, channels), (4, 3, 3))
        self.assertEqual(len(samples), 4 * 3 * 3)


class TestSlidesTotalLimit(unittest.TestCase):

    def test_download_stops_once_total_limit_is_reached(self):
        directory = tempfile.mkdtemp(prefix="zju-slides-")
        os.environ["ZJU_WORKSPACE"] = directory
        payload = b"\xff\xd8\xff" + b"x" * 100
        deck = [
            {"page": index, "image_url": f"https://media.cmc.zju.edu.cn/{index}.jpg"}
            for index in range(10)
        ]
        diagnostics = []
        try:
            with mock.patch.object(slides, "_fetch_bytes", return_value=payload), \
                    mock.patch.object(slides, "MAX_TOTAL_BYTES", 250):
                summary = slides.download_slides(
                    deck, directory, workers=1, diagnostics=diagnostics
                )
        finally:
            os.environ.pop("ZJU_WORKSPACE", None)
            shutil.rmtree(directory, ignore_errors=True)
        self.assertLess(summary["downloaded"], len(deck))
        self.assertGreater(summary["downloaded"], 0)
        self.assertTrue(any("上限" in item for item in diagnostics), diagnostics)


class TestDownloadLimit(unittest.TestCase):

    class FakeResponse:
        def __init__(self, chunks, length="0"):
            self._chunks = list(chunks)
            self.headers = {"Content-Length": length}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, _size):
            return self._chunks.pop(0) if self._chunks else b""

    def test_oversized_download_is_aborted_and_partial_file_removed(self):
        directory = tempfile.mkdtemp(prefix="zju-download-")
        target = os.path.join(directory, "typst.zip")
        response = self.FakeResponse([b"x" * 600, b"x" * 600])
        try:
            with mock.patch.object(deps, "MAX_DOWNLOAD_BYTES", 1000), \
                    mock.patch("urllib.request.urlopen", return_value=response):
                with self.assertRaises(RuntimeError) as caught:
                    deps._download("https://mirror.example.com/typst.zip", target, retries=1)
            self.assertIn("上限", str(caught.exception))
            self.assertFalse(os.path.exists(target), "半成品必须删除")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_content_length_over_limit_is_rejected_before_reading(self):
        directory = tempfile.mkdtemp(prefix="zju-download-")
        target = os.path.join(directory, "typst.zip")
        response = self.FakeResponse([], length=str(4096))
        try:
            with mock.patch.object(deps, "MAX_DOWNLOAD_BYTES", 1024), \
                    mock.patch("urllib.request.urlopen", return_value=response):
                with self.assertRaises(RuntimeError):
                    deps._download("https://mirror.example.com/typst.zip", target, retries=1)
        finally:
            shutil.rmtree(directory, ignore_errors=True)


class TestSafeMembers(unittest.TestCase):

    def test_zip_traversal_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../evil.exe", b"x")
        buffer.seek(0)
        with zipfile.ZipFile(buffer) as archive:
            with self.assertRaises(ValueError):
                deps._safe_members(archive, tempfile.gettempdir())

    def test_tar_symlink_is_rejected(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            info = tarfile.TarInfo("typst")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r:") as archive:
            with self.assertRaises(ValueError) as caught:
                deps._safe_members(archive, tempfile.gettempdir())
        self.assertIn("链接", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
