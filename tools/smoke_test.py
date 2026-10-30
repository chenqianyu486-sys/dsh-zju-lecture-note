#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smoke test for the installed plugin package.

Starts the packaged MCP server exactly the way a host does (``node
server.mjs``), then speaks JSON-RPC over stdio and performs a real transcript
fetch. This proves the shipped artifact works, not just the source tree.

Usage:
    python tools/smoke_test.py [--dir <installed plugin dir>] [--sub-id 123456]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

DEFAULT_DIR = os.path.join(
    os.environ.get("MINIMAX_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".minimax"),
    "plugins",
    "zju-lecture",
)


class SmokeError(Exception):
    pass


class Client:
    def __init__(self, command, cwd):
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", cwd=cwd,
        )

    def call(self, payload, expect_reply=True):
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        if not expect_reply:
            return None
        line = self.process.stdout.readline()
        if not line.strip():
            raise SmokeError("服务器没有返回响应（可能已退出）")
        return json.loads(line)

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=10)
        except Exception:
            self.process.kill()
        for stream in (self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="已安装插件包的端到端冒烟测试")
    parser.add_argument("--dir", default=DEFAULT_DIR, help="插件包目录")
    parser.add_argument("--sub-id", default="123456", help="用于真实抓取的 sub_id")
    parser.add_argument("--check-cookie", action="store_true",
                        help="额外调用 zju_read_browser_cookie，验证登录态读取路径的报错是否可执行")
    args = parser.parse_args()

    package_dir = os.path.abspath(args.dir)
    launcher = os.path.join(package_dir, "server.mjs")
    if not os.path.isfile(launcher):
        print(f"FAIL: 找不到启动器 {launcher}")
        return 1

    print(f"[smoke] 包目录: {package_dir}")
    client = Client(["node", launcher], package_dir)
    checks = []

    try:
        init = client.call({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "smoke", "version": "0"}},
        })
        server_info = init["result"]["serverInfo"]
        checks.append(("initialize", True, f"{server_info['name']} v{server_info['version']}"))
        print(f"[smoke] initialize -> {server_info}")

        client.call({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)

        listed = client.call({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = [tool["name"] for tool in listed["result"]["tools"]]
        expected = [
            "zju_parse_url",
            "zju_fetch_transcript",
            "zju_fetch_slides",
            "zju_extract_courseware",
            "zju_get_video_url",
            "zju_read_browser_cookie",
            "zju_check_note",
        ]
        missing = [name for name in expected if name not in names]
        checks.append(("tools/list", not missing,
                       f"{len(names)} 个工具: {', '.join(names)}"
                       + (f" | 缺失: {missing}" if missing else "")))
        print(f"[smoke] tools/list -> {names}")

        parsed = client.call({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "zju_parse_url",
                       "arguments": {"url": f"https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id={args.sub_id}"}},
        })
        payload = json.loads(parsed["result"]["content"][0]["text"])
        ok = payload.get("sub_id") == args.sub_id
        checks.append(("zju_parse_url", ok, f"sub_id={payload.get('sub_id')}"))
        print(f"[smoke] zju_parse_url -> {payload}")

        fetched = client.call({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "zju_fetch_transcript",
                       "arguments": {"url_or_sub_id": args.sub_id,
                                     "view_format": "per_minute",
                                     "start_minute": 5, "end_minute": 7}},
        })
        text = fetched["result"]["content"][0]["text"]
        ok = not fetched["result"].get("isError") and "总句数" in text
        checks.append(("zju_fetch_transcript", ok, f"{len(text)} 字符"))
        print(f"[smoke] zju_fetch_transcript -> {text[:180].replace(chr(10), ' | ')}")

        if args.check_cookie:
            cookie = client.call({
                "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "zju_read_browser_cookie", "arguments": {}},
            })
            cookie_text = cookie["result"]["content"][0]["text"]
            actionable = any(hint in cookie_text for hint in ("退出 Edge", "没有", "无法", "未找到"))
            checks.append(("zju_read_browser_cookie", actionable,
                           cookie_text.replace("\n", " | ")[:160]))
            print(f"[smoke] zju_read_browser_cookie -> {cookie_text.replace(chr(10), ' | ')[:160]}")

        # The note linter must catch the failure modes that silently break a
        # rendered lecture note (a table column cut in half, unclosed math).
        note_path = os.path.join(tempfile.gettempdir(), "zju_smoke_note.md")
        with open(note_path, "w", encoding="utf-8") as handle:
            handle.write(
                "| A | B |\n| :--- | :--- |\n"
                "| $x$ | $|y|=1$ |\n\n"
                "$$z=\\frac12$$\n"
            )
        try:
            linted = client.call({
                "jsonrpc": "2.0", "id": 6, "method": "tools/call",
                "params": {"name": "zju_check_note",
                           "arguments": {"file_path": note_path}},
            })
            lint_text = linted["result"]["content"][0]["text"]
            caught = "table_bare_pipe" in lint_text and "frac_no_brace" in lint_text
            checks.append(("zju_check_note", caught, lint_text.replace("\n", " | ")[:160]))
            print(f"[smoke] zju_check_note -> {lint_text.replace(chr(10), ' | ')[:160]}")
        finally:
            if os.path.exists(note_path):
                os.unlink(note_path)

    except SmokeError as exc:
        checks.append(("protocol", False, str(exc)))
    finally:
        client.close()

    print("\n[smoke] 验证结果：")
    passed = 0
    for label, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}: {detail}")
        passed += 1 if ok else 0
    print(f"[smoke] {passed}/{len(checks)} 通过")
    return 0 if passed == len(checks) and checks else 1


if __name__ == "__main__":
    sys.exit(main())
