"""#05 回归：注销失败绝不能冒充成功——凭据残留必须如实报告。

旧实现用「删除前是否存在」判断注销成功，文件被占用删不掉时仍报「已清除」，
钥匙串锁定时又误报「本机没有保存的登录态」。这里验证以删除后的真实状态为准，
且 MCP 标记 isError、CLI 以退出码 1 结束。只用合成凭据与隔离临时目录。
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import mcp_server  # noqa: E402
from zju_lecture import browser_login, cli, credential_store  # noqa: E402
from zju_lecture.credential_store import StoreUnavailable  # noqa: E402


class _Backend:
    """最小后端替身：clear() 要么返回布尔，要么抛 StoreUnavailable。"""

    def __init__(self, name, cleared=False, error=""):
        self.name = name
        self._cleared = cleared
        self._error = error

    def clear(self):
        if self._error:
            raise StoreUnavailable(self._error)
        return self._cleared


class TestClearSessionTruth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="zju-logout-")
        self.addCleanup(self.tmp.cleanup)
        self.login = os.path.join(self.tmp.name, "login")
        env = mock.patch.dict(os.environ, {"ZJU_LOGIN_DIR": self.login})
        env.start()
        self.addCleanup(env.stop)

    def _write_legacy_file(self):
        os.makedirs(self.login, exist_ok=True)
        path = browser_login.session_file()
        with open(path, "wb") as handle:
            handle.write(b"synthetic")
        return path

    def test_backend_failure_is_not_reported_as_success(self):
        backend = _Backend("keychain", error="synthetic locked")
        with mock.patch.object(credential_store, "backend", return_value=backend):
            result = browser_login.clear_session(delete_profile=False)
        self.assertFalse(result["session_removed"])
        self.assertTrue(result["backend_error"])

    def test_undeletable_legacy_file_is_reported(self):
        path = self._write_legacy_file()
        with mock.patch.object(credential_store, "backend", return_value=_Backend("memory")), \
             mock.patch.object(browser_login, "_secure_remove", return_value=None):
            result = browser_login.clear_session(delete_profile=False)
        self.assertFalse(result["session_removed"])
        self.assertIn("未能删除", result["backend_error"])
        self.assertTrue(os.path.lexists(path))

    def test_removed_legacy_file_reports_success(self):
        path = self._write_legacy_file()
        with mock.patch.object(credential_store, "backend", return_value=_Backend("memory")):
            result = browser_login.clear_session(delete_profile=False)
        self.assertTrue(result["session_removed"])
        self.assertEqual(result["backend_error"], "")
        self.assertFalse(os.path.lexists(path))


FAILED_CLEAR = {
    "session_removed": False, "backend": "dpapi", "backend_error": "store unavailable",
    "profile_removed": False, "profile_error": "", "profile_path": "synthetic-profile",
}


class TestLogoutReporting(unittest.TestCase):
    def test_mcp_marks_cleanup_failure_as_error(self):
        with mock.patch.object(mcp_server, "clear_session", return_value=FAILED_CLEAR):
            response = mcp_server.handle_request({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "zju_login", "arguments": {"clear": True, "confirm": True}},
            })
        self.assertTrue(response["result"]["isError"])
        text = response["result"]["content"][0]["text"]
        self.assertIn("清理未完成", text)
        self.assertNotIn("本机没有保存", text)

    def test_cli_exits_nonzero_without_claiming_no_session(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "clear_session", return_value=FAILED_CLEAR), \
             mock.patch("sys.argv", ["zju-lecture", "login", "--clear"]), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                cli.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("清理未完成", out.getvalue() + err.getvalue())
        self.assertNotIn("本机没有保存", out.getvalue())


if __name__ == "__main__":
    unittest.main()