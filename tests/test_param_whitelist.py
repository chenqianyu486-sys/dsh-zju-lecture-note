#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具参数白名单（安全审查 P2-1 / 7.7）。

dsh 0.2.x 不为工具参数生成根级封闭声明，`validateArgs()` 会接受未声明的
``cookie`` / ``token`` / ``password`` 字段。Python 以前直接忽略它们，但宿主
可能已经把值写进了调用日志。现在 dispatch 前做允许键校验：出现未知键就
抛 ValueError，工具本身不执行，错误里只出现键名。
"""

import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mcp_server  # noqa: E402
from mcp_server import TOOLS, handle_request, handle_tool_call  # noqa: E402


class TestWhitelist(unittest.TestCase):

    def test_undeclared_parameter_is_rejected_before_dispatch(self):
        with mock.patch.object(mcp_server, "_dispatch_tool") as dispatch:
            with self.assertRaises(ValueError) as caught:
                handle_tool_call(
                    "zju_parse_url", {"url": "123", "cookie": "SECRET-COOKIE-VALUE"}
                )
        self.assertIn("未知参数: cookie", str(caught.exception))
        self.assertNotIn("SECRET-COOKIE-VALUE", str(caught.exception))
        dispatch.assert_not_called()

    def test_all_unknown_keys_are_named_once(self):
        with mock.patch.object(mcp_server, "_dispatch_tool"):
            with self.assertRaises(ValueError) as caught:
                handle_tool_call(
                    "zju_fetch_transcript",
                    {"url_or_sub_id": "1", "token": "t", "password": "p"},
                )
        message = str(caught.exception)
        self.assertIn("password", message)
        self.assertIn("token", message)

    def test_no_parameter_tool_rejects_any_argument(self):
        with mock.patch.object(mcp_server, "_dispatch_tool"):
            with self.assertRaises(ValueError):
                handle_tool_call("zju_read_browser_cookie", {"cookie": "x"})

    def test_declared_parameters_still_work(self):
        parsed = json.loads(handle_tool_call("zju_parse_url", {"url": "123456"}))
        self.assertEqual(parsed["sub_id"], "123456")

    def test_json_rpc_reports_it_as_a_tool_error(self):
        response = handle_request({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "zju_parse_url",
                "arguments": {"url": "123", "cookie": "SECRET-COOKIE-VALUE"},
            },
        })
        result = response["result"]
        self.assertTrue(result["isError"])
        text = result["content"][0]["text"]
        self.assertIn("未知参数: cookie", text)
        self.assertNotIn("SECRET-COOKIE-VALUE", text)


class TestGeneratedSchemaNotes(unittest.TestCase):

    def test_generated_tools_explain_where_the_root_is_enforced(self):
        path = os.path.join(ROOT, "lib", "tools.js")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("additionalProperties", text)
        self.assertIn("mcp_server.handle_tool_call", text)

    def test_every_tool_rejects_an_undeclared_key(self):
        for tool in TOOLS:
            with self.subTest(tool=tool["name"]):
                with self.assertRaises(ValueError):
                    handle_tool_call(tool["name"], {"__unknown__": 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
