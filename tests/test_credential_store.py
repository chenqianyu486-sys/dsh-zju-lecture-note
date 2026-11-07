#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Credential-store regression tests (2.2.8 R5).

The rule under test is absolute: **no platform may write the classroom session
as plaintext**. Windows uses DPAPI, macOS the login Keychain, Linux Secret
Service; when none is available the session stays in memory. These tests drive
the macOS / Linux backends through an injected runner, so the behaviour is
covered on any operating system without touching a real keyring.
"""

import json
import os
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from zju_lecture import browser_login, credential_store  # noqa: E402

COOKIE = "sid=classroom-session; _token=" + "T" * 40
PAYLOAD = {
    "version": 1,
    "saved_at": 1700000000,
    "browser": "Microsoft Edge",
    "cookie": COOKIE,
}


class FakeKeychain:
    """Minimal ``security`` replacement: one item, stored as the -w value."""

    def __init__(self, stderr_on_save="", code_on_save=0):
        self.value = None
        self.calls = []
        self.stderr_on_save = stderr_on_save
        self.code_on_save = code_on_save

    def __call__(self, argv, stdin_text=None, timeout=10.0):
        argv = list(argv)
        self.calls.append((argv, stdin_text))
        if argv[-1] == "-i":
            parts = shlex.split(stdin_text or "")
            if parts and parts[0] == "add-generic-password":
                if "-w" in parts:
                    self.value = parts[parts.index("-w") + 1]
            return self.code_on_save, "security> ", self.stderr_on_save
        if "find-generic-password" in argv:
            if self.value is None:
                return 44, "", ""
            return 0, self.value + "\n", ""
        if "delete-generic-password" in argv:
            had = self.value is not None
            self.value = None
            return (0 if had else 44), "", ""
        return 1, "", "unexpected command"

    @property
    def stdin_commands(self):
        return [text for argv, text in self.calls if argv and argv[-1] == "-i"]

    @property
    def argv_text(self):
        return " ".join(" ".join(argv) for argv, _text in self.calls)


class FakeSecretTool:
    """Minimal ``secret-tool`` replacement; the secret arrives on stdin."""

    def __init__(self, stderr="", code=0):
        self.value = None
        self.calls = []
        self.stderr = stderr
        self.code = code

    def __call__(self, argv, stdin_text=None, timeout=10.0):
        argv = list(argv)
        self.calls.append((argv, stdin_text))
        action = argv[1] if len(argv) > 1 else ""
        if action == "store":
            if self.code:
                return self.code, "", self.stderr
            self.value = stdin_text
            return 0, "", ""
        if action == "lookup":
            if self.value is None:
                return 1, "", self.stderr
            return 0, self.value + "\n", ""
        if action == "clear":
            had = self.value is not None
            self.value = None
            return (0 if had else 1), "", ""
        return 1, "", "unexpected command"

    @property
    def argv_text(self):
        return " ".join(" ".join(argv) for argv, _text in self.calls)


class TestSecretFormat(unittest.TestCase):

    def test_roundtrip_uses_a_whitespace_free_charset(self):
        secret = credential_store.encode_secret(PAYLOAD)
        self.assertTrue(secret.startswith(credential_store.SECRET_PREFIX))
        self.assertFalse(any(char.isspace() for char in secret))
        self.assertEqual(credential_store.decode_secret(secret), PAYLOAD)

    def test_garbage_is_rejected(self):
        for value in ("", "not-ours", credential_store.SECRET_PREFIX + "!!!", "x" * 100):
            with self.subTest(value=value):
                self.assertIsNone(credential_store.decode_secret(value))

    def test_oversized_payload_is_refused(self):
        huge = dict(PAYLOAD, cookie="x" * (credential_store.SESSION_MAX_BYTES + 10))
        with self.assertRaises(credential_store.StoreUnavailable):
            credential_store.encode_secret(huge)

    def test_legacy_plaintext_blob_is_readable_for_migration_only(self):
        raw = json.dumps(PAYLOAD).encode("utf-8")
        mode, payload = credential_store.decode_legacy_blob(
            credential_store.LEGACY_BLOB_MAGIC + b"P" + raw
        )
        self.assertEqual(mode, "P")
        self.assertEqual(payload, PAYLOAD)

    def test_unknown_legacy_blob_is_rejected(self):
        self.assertIsNone(credential_store.decode_legacy_blob(b"not-a-session"))
        self.assertIsNone(
            credential_store.decode_legacy_blob(credential_store.LEGACY_BLOB_MAGIC + b"X{}")
        )


class TestKeychainBackend(unittest.TestCase):

    def test_save_uses_update_flag_and_never_puts_the_secret_in_argv(self):
        fake = FakeKeychain()
        backend = credential_store.KeychainBackend(fake)
        backend.save(PAYLOAD)

        command = fake.stdin_commands[0]
        self.assertIn("add-generic-password", command)
        self.assertIn("-U", command)
        self.assertIn(credential_store.SERVICE, command)
        self.assertIn(credential_store.ACCOUNT, command)
        self.assertIn(credential_store.encode_secret(PAYLOAD), command)
        # The cookie (and the encoded secret) must never be an argv element.
        self.assertNotIn(COOKIE, fake.argv_text)
        self.assertNotIn(credential_store.encode_secret(PAYLOAD), fake.argv_text)

    def test_roundtrip_and_clear(self):
        fake = FakeKeychain()
        backend = credential_store.KeychainBackend(fake)
        self.assertTrue(backend.save(PAYLOAD))
        self.assertEqual(backend.load(), PAYLOAD)
        self.assertTrue(backend.clear())
        self.assertIsNone(backend.load())

    def test_missing_item_is_not_an_error(self):
        backend = credential_store.KeychainBackend(FakeKeychain())
        self.assertIsNone(backend.load())
        self.assertFalse(backend.clear())

    def test_exit_code_45_reports_a_failure(self):
        fake = FakeKeychain(code_on_save=45)
        backend = credential_store.KeychainBackend(fake)
        with self.assertRaises(credential_store.StoreUnavailable) as caught:
            backend.save(PAYLOAD)
        self.assertIn("45", caught.exception.reason)

    def test_stderr_with_exit_zero_is_treated_as_failure(self):
        # Some macOS builds print the error but still exit 0.
        fake = FakeKeychain(stderr_on_save="security: SecKeychainItemCreate failed")
        backend = credential_store.KeychainBackend(fake)
        with self.assertRaises(credential_store.StoreUnavailable) as caught:
            backend.save(PAYLOAD)
        self.assertIn("返回码 0", caught.exception.reason)

    def test_readback_mismatch_deletes_the_item(self):
        fake = FakeKeychain()
        backend = credential_store.KeychainBackend(fake)
        with mock.patch.object(backend, "load", return_value={"other": 1}):
            with self.assertRaises(credential_store.StoreUnavailable) as caught:
                backend.save(PAYLOAD)
        self.assertIn("回读不一致", caught.exception.reason)

    def test_save_refuses_a_secret_with_whitespace(self):
        backend = credential_store.KeychainBackend(FakeKeychain())
        with mock.patch.object(
            credential_store, "encode_secret", return_value="has a space"
        ):
            with self.assertRaises(credential_store.StoreUnavailable):
                backend.save(PAYLOAD)


class TestSecretToolBackend(unittest.TestCase):

    def test_store_puts_the_secret_on_stdin_only(self):
        fake = FakeSecretTool()
        backend = credential_store.SecretToolBackend(fake)
        backend.save(PAYLOAD)
        store_calls = [call for call in fake.calls if call[0][1] == "store"]
        self.assertEqual(store_calls[0][1], credential_store.encode_secret(PAYLOAD))
        self.assertNotIn(COOKIE, fake.argv_text)
        self.assertNotIn(credential_store.encode_secret(PAYLOAD), fake.argv_text)

    def test_roundtrip_and_clear(self):
        fake = FakeSecretTool()
        backend = credential_store.SecretToolBackend(fake)
        self.assertTrue(backend.save(PAYLOAD))
        self.assertEqual(backend.load(), PAYLOAD)
        self.assertTrue(backend.clear())
        self.assertIsNone(backend.load())

    def test_unlocked_keyring_failure_is_reported(self):
        fake = FakeSecretTool(stderr="Cannot autolaunch D-Bus", code=1)
        backend = credential_store.SecretToolBackend(fake)
        with self.assertRaises(credential_store.StoreUnavailable) as caught:
            backend.save(PAYLOAD)
        self.assertIn("D-Bus", caught.exception.reason)

    def test_lookup_failure_with_stderr_is_reported(self):
        fake = FakeSecretTool(stderr="The name org.freedesktop.secrets was not provided")
        backend = credential_store.SecretToolBackend(fake)
        with self.assertRaises(credential_store.StoreUnavailable):
            backend.load()

    def test_empty_lookup_is_not_an_error(self):
        backend = credential_store.SecretToolBackend(FakeSecretTool())
        self.assertIsNone(backend.load())


class TestRunner(unittest.TestCase):

    def test_timeout_becomes_store_unavailable(self):
        with self.assertRaises(credential_store.StoreUnavailable) as caught:
            credential_store.run_command(
                [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2
            )
        self.assertIn("超时", caught.exception.reason)

    def test_missing_binary_becomes_store_unavailable(self):
        with self.assertRaises(credential_store.StoreUnavailable):
            credential_store.run_command(["zju-lecture-no-such-binary-xyz"])

    def test_captures_stdout_and_exit_code(self):
        code, out, _err = credential_store.run_command(
            [sys.executable, "-c", "print('hi')"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "hi")


class TestBackendSelection(unittest.TestCase):

    def test_windows_is_always_dpapi(self):
        backend = credential_store.default_backend(platform="win32")
        self.assertEqual(backend.name, "dpapi")
        self.assertTrue(backend.persistent)

    def test_macos_prefers_the_keychain(self):
        with mock.patch.object(credential_store, "_which", return_value="/usr/bin/security"):
            backend = credential_store.default_backend(platform="darwin")
        self.assertEqual(backend.name, "keychain")
        self.assertTrue(backend.persistent)

    def test_macos_without_security_stays_in_memory(self):
        with mock.patch.object(credential_store, "_which", return_value=None):
            backend = credential_store.default_backend(platform="darwin")
        self.assertEqual(backend.name, "memory")
        self.assertFalse(backend.persistent)

    def test_linux_prefers_secret_tool(self):
        with mock.patch.object(credential_store, "_which", return_value="/usr/bin/secret-tool"):
            backend = credential_store.default_backend(platform="linux")
        self.assertEqual(backend.name, "secret-service")

    def test_linux_without_secret_tool_stays_in_memory_and_explains(self):
        with mock.patch.object(credential_store, "_which", return_value=None):
            backend = credential_store.default_backend(platform="linux")
        self.assertEqual(backend.name, "memory")
        self.assertIn("libsecret", backend.describe())

    def test_memory_mode_never_persists(self):
        with mock.patch.dict(os.environ, {"ZJU_LOGIN_STORAGE": "memory"}):
            backend = credential_store.default_backend(platform="win32")
        self.assertEqual(backend.name, "memory")
        self.assertFalse(backend.persistent)

    def test_memory_backend_explains_the_cli_semantics(self):
        backend = credential_store.MemoryBackend("test")
        self.assertIn("仅当前进程有效", backend.advice())
        self.assertIn("ZJU_COOKIE_FILE", backend.advice())


class TestNoPlaintextPaths(unittest.TestCase):
    """The end-to-end rule: the plugin never drops a credential file."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="zju-store-")
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.env = mock.patch.dict(
            os.environ, {"ZJU_LOGIN_DIR": self.directory}, clear=False
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_posix_backend_creates_no_session_file(self):
        fake = FakeKeychain()
        backend = credential_store.KeychainBackend(fake)
        with mock.patch.object(credential_store, "backend", return_value=backend):
            browser_login.save_session(COOKIE)
        self.assertFalse(os.path.exists(browser_login.session_file()))
        self.assertEqual(
            [name for name in os.listdir(self.directory) if name.endswith(".tmp")], []
        )

    def test_legacy_plaintext_is_migrated_and_deleted(self):
        payload = dict(PAYLOAD)
        raw = json.dumps(payload).encode("utf-8")
        with open(browser_login.session_file(), "wb") as handle:
            handle.write(credential_store.LEGACY_BLOB_MAGIC + b"P" + raw)

        fake = FakeKeychain()
        backend = credential_store.KeychainBackend(fake)
        with mock.patch.object(credential_store, "backend", return_value=backend):
            self.assertEqual(browser_login.load_session_cookie(), COOKIE)

        self.assertFalse(os.path.exists(browser_login.session_file()))
        self.assertEqual(backend.load(), payload)

    def test_legacy_plaintext_is_deleted_even_when_the_backend_fails(self):
        raw = json.dumps(PAYLOAD).encode("utf-8")
        with open(browser_login.session_file(), "wb") as handle:
            handle.write(credential_store.LEGACY_BLOB_MAGIC + b"P" + raw)

        backend = credential_store.MemoryBackend()
        with mock.patch.object(
            backend, "save", side_effect=credential_store.StoreUnavailable("locked")
        ), mock.patch.object(credential_store, "backend", return_value=backend):
            self.assertEqual(browser_login.load_session_cookie(), COOKIE)

        self.assertFalse(os.path.exists(browser_login.session_file()))

    def test_clear_removes_backend_item_file_and_profile(self):
        fake = FakeKeychain()
        backend = credential_store.KeychainBackend(fake)
        backend.save(PAYLOAD)
        with open(browser_login.session_file(), "wb") as handle:
            handle.write(credential_store.LEGACY_BLOB_MAGIC + b"P" + b"{}")
        os.makedirs(browser_login.profile_dir(), exist_ok=True)

        with mock.patch.object(credential_store, "backend", return_value=backend):
            result = browser_login.clear_session(delete_profile=True)

        self.assertTrue(result["session_removed"])
        self.assertTrue(result["profile_removed"])
        self.assertIsNone(backend.load())
        self.assertFalse(os.path.exists(browser_login.session_file()))
        self.assertFalse(os.path.exists(browser_login.profile_dir()))

    def test_summary_names_the_backend_without_the_value(self):
        backend = credential_store.MemoryBackend("测试")
        with mock.patch.object(credential_store, "backend", return_value=backend):
            browser_login.save_session(COOKIE)
            summary = browser_login.session_summary()
        self.assertTrue(summary["available"])
        self.assertEqual(summary["backend"], "memory")
        self.assertFalse(summary["persistent"])
        self.assertNotIn(COOKIE, repr(summary))


@unittest.skipUnless(sys.platform == "win32", "DPAPI 只在 Windows 上可用")
class TestWindowsPlaintextUpgrade(unittest.TestCase):
    """A legacy plaintext blob on Windows is rewritten through DPAPI in place."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="zju-win-upgrade-")
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.env = mock.patch.dict(
            os.environ, {"ZJU_LOGIN_DIR": self.directory, "ZJU_LOGIN_STORAGE": "os"}
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_plaintext_blob_becomes_a_dpapi_blob(self):
        raw = json.dumps(PAYLOAD).encode("utf-8")
        path = browser_login.session_file()
        with open(path, "wb") as handle:
            handle.write(credential_store.LEGACY_BLOB_MAGIC + b"P" + raw)

        self.assertEqual(browser_login.load_session_cookie(), COOKIE)

        with open(path, "rb") as handle:
            blob = handle.read()
        marker = blob[len(credential_store.LEGACY_BLOB_MAGIC):
                      len(credential_store.LEGACY_BLOB_MAGIC) + 1]
        self.assertEqual(marker, b"D")
        self.assertNotIn(COOKIE.encode("utf-8"), blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
