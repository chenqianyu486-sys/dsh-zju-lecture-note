"""A credential-store failure must not look like a successful logout."""
import contextlib
import io
import unittest
from unittest import mock

import mcp_server
from zju_lecture import cli


FAILED_CLEAR = {
    "session_removed": False, "backend": "dpapi", "backend_error": "store unavailable",
    "profile_removed": False, "profile_error": "", "profile_path": "synthetic-profile",
}


class TestLogoutReporting(unittest.TestCase):
    def test_mcp_marks_cleanup_failure_as_an_error(self):
        with mock.patch.object(mcp_server, "clear_session", return_value=FAILED_CLEAR):
            response = mcp_server.handle_request({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "zju_login", "arguments": {"clear": True, "confirm": True}},
            })
        self.assertTrue(response["result"]["isError"])
        text = response["result"]["content"][0]["text"]
        self.assertIn("清理未完成", text)
        self.assertNotIn("本机没有保存", text)

    def test_cli_returns_failure_without_claiming_no_session(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "clear_session", return_value=FAILED_CLEAR), \
             mock.patch("sys.argv", ["zju-lecture", "login", "--clear"]), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                cli.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("清理未完成", out.getvalue() + err.getvalue())
        self.assertNotIn("本机没有保存", out.getvalue())
