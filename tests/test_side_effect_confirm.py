#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""副作用确认（安全审查 P2-2）。

三个工具的一个分支会真正改变本机状态：
* ``zju_login(clear=true)`` 删除登录态与浏览器配置；
* ``zju_doctor(install=true)`` 下载安装 Typst；
* ``zju_fetch_slides(download=true)`` 批量下载截图并写盘。

模型一次误调用就会造成不可逆的本地副作用。现在这些分支必须显式
``confirm=true``；缺失时只返回一句可执行提示，不调用底层、不写文件。
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mcp_server  # noqa: E402
from mcp_server import TOOLS, handle_tool_call  # noqa: E402
from zju_lecture import browser_login  # noqa: E402

COOKIE = "sid=abc123; _token=" + "T" * 40


def schema(name):
    return next(item for item in TOOLS if item["name"] == name)["inputSchema"]


class TestSchemaDeclaresConfirm(unittest.TestCase):

    def test_side_effect_tools_expose_confirm(self):
        for name in ("zju_login", "zju_doctor", "zju_fetch_slides"):
            with self.subTest(name=name):
                properties = schema(name)["properties"]
                self.assertIn("confirm", properties)
                self.assertEqual(properties["confirm"]["type"], "boolean")
                self.assertIs(properties["confirm"].get("default"), False)
                self.assertIn("confirm=true", properties["confirm"]["description"])


class TestLoginClearNeedsConfirm(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="zju-confirm-login-")
        self.env = mock.patch.dict(os.environ, {"ZJU_LOGIN_DIR": self.directory})
        self.env.start()
        browser_login.save_session(COOKIE)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_clear_without_confirm_keeps_the_session(self):
        with mock.patch.object(mcp_server, "clear_session") as clear:
            output = handle_tool_call("zju_login", {"clear": True})
        self.assertIn("confirm=true", output)
        clear.assert_not_called()
        self.assertTrue(os.path.exists(browser_login.session_file()))

    def test_clear_with_confirm_removes_the_session(self):
        output = handle_tool_call("zju_login", {"clear": True, "confirm": True})
        self.assertIn("已清除", output)
        self.assertFalse(os.path.exists(browser_login.session_file()))


class TestDoctorInstallNeedsConfirm(unittest.TestCase):

    def test_install_without_confirm_does_not_download(self):
        with mock.patch.object(mcp_server, "_doctor_report") as report:
            output = handle_tool_call("zju_doctor", {"install": True})
        self.assertIn("confirm=true", output)
        report.assert_not_called()

    def test_install_with_confirm_reaches_the_report(self):
        with mock.patch.object(mcp_server, "_doctor_report", return_value="ok") as report:
            output = handle_tool_call("zju_doctor", {"install": True, "confirm": True})
        self.assertEqual(output, "ok")
        report.assert_called_once_with(True, False)

    def test_plain_doctor_does_not_need_confirm(self):
        with mock.patch.object(mcp_server, "_doctor_report", return_value="ok") as report:
            handle_tool_call("zju_doctor", {"login": True})
        report.assert_called_once_with(False, True)


class TestSlidesDownloadNeedsConfirm(unittest.TestCase):

    def setUp(self):
        self.workspace = tempfile.mkdtemp(prefix="zju-confirm-slides-")
        self.env = mock.patch.dict(
            os.environ,
            {
                "ZJU_WORKSPACE": self.workspace,
                "ZJU_ENABLE_SLIDES": "1",
                "ZJU_EMBED_SLIDES": "1",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.workspace, ignore_errors=True)

    def test_explicit_download_without_confirm_does_not_touch_network_or_disk(self):
        with mock.patch.object(mcp_server, "fetch_slides") as fetch:
            output = handle_tool_call(
                "zju_fetch_slides",
                {"url_or_sub_id": "123456", "download": True},
            )
        self.assertIn("confirm=true", output)
        fetch.assert_not_called()
        self.assertEqual(os.listdir(self.workspace), [])

    def test_setting_driven_download_also_needs_confirm(self):
        with mock.patch.object(mcp_server, "fetch_slides") as fetch:
            output = handle_tool_call("zju_fetch_slides", {"url_or_sub_id": "123456"})
        self.assertIn("confirm=true", output)
        fetch.assert_not_called()

    def test_metadata_only_does_not_need_confirm(self):
        slides = [{
            "page": 1,
            "image_url": "https://media.cmc.zju.edu.cn/1.jpg",
            "text": "",
        }]
        with mock.patch.object(
            mcp_server, "_resolve_cookie", return_value=("S=1", None, "cache", None)
        ), mock.patch.object(mcp_server, "fetch_slides", return_value=slides):
            output = handle_tool_call(
                "zju_fetch_slides",
                {"url_or_sub_id": "123456", "download": False},
            )
        self.assertNotIn("confirm=true", output)
        self.assertIn("不是文字层", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
