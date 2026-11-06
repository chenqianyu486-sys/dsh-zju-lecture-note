#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for the v2.2.5 one-click login window.

Covers the non-interactive part of the feature:

* the saved session (DPAPI on Windows, 0600 on POSIX) round-trips and can be
  cleared; a tampered file is rejected;
* CDP cookie rows are filtered to the classroom host + the domain-scoped
  ``.zju.edu.cn`` token, never to lookalikes or other ZJU subdomains;
* the login URL only accepts ``https://*.zju.edu.cn``;
* ``_resolve_cookie`` prefers explicit host config, then the saved session,
  then Edge; an invalid session is removed after a second 401;
* ``zju_login`` is a core tool with no secret parameters, and the clear action
  deletes the local session without echoing anything;
* a window that cannot start fails with a machine-readable reason.
"""

import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import mcp_server  # noqa: E402
from zju_lecture import browser_login  # noqa: E402

COOKIE = "sid=classroom-session; _token=tok-123456"
TOKEN = "tok-123456"


class LoginDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="zju-login-test-")
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(
            os.environ,
            {
                "ZJU_LOGIN_DIR": self.tmp.name,
                "ZJU_COOKIE": "",
                "ZJU_COOKIE_FILE": "",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        mcp_server._COOKIE_CACHE.clear()
        self.addCleanup(mcp_server._COOKIE_CACHE.clear)


class TestSessionStore(LoginDirTestCase):
    def test_roundtrip_and_summary_never_contains_the_value(self):
        path = browser_login.save_session(COOKIE, browser="test-browser")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(browser_login.load_session_cookie(), COOKIE)
        summary = browser_login.session_summary()
        self.assertTrue(summary["available"])
        self.assertEqual(summary["cookie_count"], 2)
        self.assertIn("_token", summary["names"])
        self.assertNotIn(TOKEN, repr(summary))

    def test_windows_uses_dpapi_and_posix_uses_a_private_file(self):
        browser_login.save_session(COOKIE)
        with open(browser_login.session_file(), "rb") as handle:
            raw = handle.read()
        self.assertTrue(raw.startswith(browser_login.SESSION_MAGIC))
        mode = raw[len(browser_login.SESSION_MAGIC): len(browser_login.SESSION_MAGIC) + 1]
        if sys.platform == "win32":
            self.assertEqual(mode, b"D")
        else:
            self.assertEqual(mode, b"P")
            file_mode = stat.S_IMODE(os.stat(browser_login.session_file()).st_mode)
            self.assertEqual(file_mode, 0o600)

    def test_tampered_file_is_rejected(self):
        browser_login.save_session(COOKIE)
        with open(browser_login.session_file(), "wb") as handle:
            handle.write(b"not-a-session")
        self.assertIsNone(browser_login.load_session_cookie())
        self.assertFalse(browser_login.session_summary()["available"])

    def test_cookie_without_token_is_rejected(self):
        with self.assertRaises(browser_login.LoginError) as caught:
            browser_login.save_session("sid=only")
        self.assertEqual(caught.exception.reason, "save_failed")

    def test_clear_removes_session_and_profile(self):
        browser_login.save_session(COOKIE)
        profile = browser_login.profile_dir()
        os.makedirs(profile, exist_ok=True)
        with open(os.path.join(profile, "marker"), "w", encoding="utf-8") as handle:
            handle.write("x")
        result = browser_login.clear_session(delete_profile=True)
        self.assertTrue(result["session_removed"])
        self.assertTrue(result["profile_removed"])
        self.assertFalse(os.path.exists(browser_login.session_file()))
        self.assertFalse(os.path.exists(profile))

    def test_login_dir_honours_the_override(self):
        self.assertEqual(
            os.path.normcase(browser_login.login_dir()),
            os.path.normcase(os.path.abspath(self.tmp.name)),
        )


class TestCookieFiltering(unittest.TestCase):
    def test_classroom_and_parent_domain_only(self):
        header = browser_login._cookie_header_from_cdp([
            {"domain": ".zju.edu.cn", "name": "_token", "value": "tok-123456"},
            {"domain": "classroom.zju.edu.cn", "name": "sid", "value": "classroom-session"},
            {"domain": "courses.zju.edu.cn", "name": "other_zju", "value": "no"},
            {"domain": "classroom.zju.edu.cn.attacker.example", "name": "bad", "value": "no"},
            {"domain": "evilclassroom.zju.edu.cn", "name": "bad2", "value": "no"},
            {"domain": "classroom.zju.edu.cn", "name": "sid", "value": "duplicate"},
            {"domain": "classroom.zju.edu.cn", "name": "empty", "value": ""},
            {"domain": "classroom.zju.edu.cn", "name": "expired", "value": "old", "expires": 1},
        ])
        self.assertEqual(header, "sid=classroom-session; _token=tok-123456")

    def test_unrelated_cookies_yield_an_empty_header(self):
        self.assertEqual(
            browser_login._cookie_header_from_cdp([
                {"domain": "example.com", "name": "x", "value": "y"},
            ]),
            "",
        )


class TestLoginUrl(LoginDirTestCase):
    def test_default_is_classroom(self):
        self.assertEqual(
            browser_login.sanitize_login_url(""),
            browser_login.DEFAULT_LOGIN_URL,
        )

    def test_http_zju_is_upgraded(self):
        self.assertEqual(
            browser_login.sanitize_login_url("http://classroom.zju.edu.cn/livingroom?sub_id=1"),
            "https://classroom.zju.edu.cn/livingroom?sub_id=1",
        )

    def test_lookalikes_are_rejected(self):
        for url in (
            "https://classroom.zju.edu.cn.attacker.example/",
            "https://zju.edu.cn.attacker.example/",
            "https://example.com/",
            "https://user:pass@classroom.zju.edu.cn/",
        ):
            with self.assertRaises(browser_login.LoginError) as caught:
                browser_login.sanitize_login_url(url)
            self.assertEqual(caught.exception.reason, "bad_url")


class TestResolveCookieOrder(LoginDirTestCase):
    def test_saved_session_is_used_before_edge(self):
        browser_login.save_session(COOKIE)
        with mock.patch.object(mcp_server, "read_edge_cookies", return_value=(None, None)) as edge:
            cookie, error, source, reason = mcp_server._resolve_cookie()
        self.assertEqual(cookie, COOKIE)
        self.assertIsNone(error)
        self.assertEqual(source, "session")
        self.assertIsNone(reason)
        edge.assert_not_called()

    def test_explicit_env_wins_over_the_saved_session(self):
        browser_login.save_session(COOKIE)
        with mock.patch.dict(os.environ, {"ZJU_COOKIE": "sid=from-env; _token=tok-env"}):
            cookie, _error, source, _reason = mcp_server._resolve_cookie()
        self.assertEqual(source, "env")
        self.assertIn("from-env", cookie)

    def test_corrupt_session_falls_back_to_edge(self):
        browser_login.save_session(COOKIE)
        with open(browser_login.session_file(), "wb") as handle:
            handle.write(b"broken")
        with mock.patch.object(mcp_server, "read_edge_cookies", return_value=("sid=edge; _token=tok-edge", None)):
            cookie, _error, source, _reason = mcp_server._resolve_cookie()
        self.assertEqual(source, "edge")
        self.assertIn("tok-edge", cookie)

    def test_forget_session_removes_disk_and_memory(self):
        browser_login.save_session(COOKIE)
        mcp_server._COOKIE_CACHE[mcp_server.DEFAULT_DOMAIN] = COOKIE
        mcp_server._forget_cookie("session")
        self.assertNotIn(mcp_server.DEFAULT_DOMAIN, mcp_server._COOKIE_CACHE)
        self.assertFalse(os.path.exists(browser_login.session_file()))


class TestLoginTool(LoginDirTestCase):
    def test_login_is_a_core_tool_without_secret_parameters(self):
        with mock.patch.dict(os.environ, {"ZJU_ENABLE_LOGIN_TOOLS": "0"}):
            names = [tool["name"] for tool in mcp_server.available_tools()]
        self.assertIn("zju_login", names)
        tool = next(item for item in mcp_server.TOOLS if item["name"] == "zju_login")
        properties = tool["inputSchema"]["properties"]
        self.assertEqual(set(properties), {"url", "timeout_seconds", "clear"})
        for forbidden in ("cookie", "password", "token", "reveal"):
            self.assertNotIn(forbidden, properties)

    def test_successful_login_keeps_the_cookie_in_memory_but_not_in_output(self):
        fake = {
            "cookie": COOKIE,
            "names": ["sid", "_token"],
            "browser": "Microsoft Edge",
            "elapsed": 3.2,
            "saved": True,
            "saved_path": os.path.join(self.tmp.name, "session.bin"),
            "save_error": "",
        }
        with mock.patch.object(mcp_server, "open_login_window", return_value=fake):
            output = mcp_server.handle_tool_call(
                "zju_login", {"url": "https://classroom.zju.edu.cn/livingroom?sub_id=1"}
            )
        self.assertIn("登录成功", output)
        self.assertIn("Microsoft Edge", output)
        self.assertNotIn(TOKEN, output)
        self.assertNotIn("_token=", output)
        self.assertEqual(mcp_server._COOKIE_CACHE[mcp_server.DEFAULT_DOMAIN], COOKIE)

    def test_no_browser_failure_is_actionable(self):
        error = browser_login.LoginError(
            "未找到可用的浏览器", "安装 Edge 或 Chrome；服务器改用 ZJU_COOKIE_FILE。", reason="no_browser"
        )
        with mock.patch.object(mcp_server, "open_login_window", side_effect=error):
            with self.assertRaises(mcp_server.ZJUAPIError) as caught:
                mcp_server.handle_tool_call("zju_login", {})
        message = str(caught.exception)
        self.assertIn("no_browser", message)
        self.assertIn("ZJU_COOKIE_FILE", message)

    def test_clear_action_removes_the_saved_session(self):
        browser_login.save_session(COOKIE)
        mcp_server._COOKIE_CACHE[mcp_server.DEFAULT_DOMAIN] = COOKIE
        output = mcp_server.handle_tool_call("zju_login", {"clear": True})
        self.assertIn("已清除", output)
        self.assertFalse(os.path.exists(browser_login.session_file()))
        self.assertNotIn(mcp_server.DEFAULT_DOMAIN, mcp_server._COOKIE_CACHE)

    def test_no_browser_environment_has_a_clear_reason(self):
        with mock.patch.dict(os.environ, {"ZJU_BROWSER_BIN": os.path.join(self.tmp.name, "missing")}):
            self.assertEqual(browser_login.browser_candidates(), [])
            with self.assertRaises(browser_login.LoginError) as caught:
                browser_login.open_login_window(timeout_s=30)
        self.assertEqual(caught.exception.reason, "no_browser")

    def test_slides_auth_failure_clears_the_saved_session(self):
        browser_login.save_session(COOKIE)

        def fake_fetch(*_args, diagnostics=None, **_kwargs):
            diagnostics.append("PPT 接口返回 HTTP 403；登录态无效或 Cookie 缺少 _token")
            return None

        with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": "1"}), \
                mock.patch.object(mcp_server, "fetch_slides", side_effect=fake_fetch):
            output = mcp_server.handle_tool_call(
                "zju_fetch_slides", {"url_or_sub_id": "https://classroom.zju.edu.cn/livingroom?sub_id=1&course_id=2"}
            )
        self.assertIn("session_expired", output)
        self.assertIn("zju_login", output)
        self.assertFalse(os.path.exists(browser_login.session_file()))


class TestDoctorAndFailureActions(LoginDirTestCase):
    def test_doctor_reports_saved_session_without_values(self):
        browser_login.save_session(COOKIE, browser="Microsoft Edge")
        report = mcp_server._doctor_report(False, check_login=True)
        self.assertIn("本机登录态: 已保存", report)
        self.assertIn("来源 session", report)
        self.assertIn("登录窗口", report)
        self.assertNotIn(TOKEN, report)

    def test_every_failure_action_prefers_the_login_window(self):
        for reason in ("abe", "locked", "no_rows", "no_credentials", "session_expired"):
            action = mcp_server.COOKIE_FAILURE_ACTIONS[reason]
            self.assertIn("zju_login", action, reason)
        # The explicit host configuration cannot be bypassed by zju_login;
        # those two actions must tell the user to fix/remove it.
        for reason in ("env_invalid", "file_unreadable"):
            self.assertIn("ZJU_", mcp_server.COOKIE_FAILURE_ACTIONS[reason], reason)


if __name__ == "__main__":
    unittest.main()
