"""Authentication review regressions; synthetic data and private temp dirs only."""

import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from zju_lecture import browser_login, cookies, credential_store


COOKIE = "sid=synthetic; _token=synthetic_review_token_123"
PAYLOAD = {"version": 1, "cookie": COOKIE}


class IsolatedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="zju-auth-review-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.enterContext(mock.patch.dict(os.environ, {"ZJU_LOGIN_DIR": str(self.root / "login")}))

    def stale_dir(self):
        path = self.root / "zju-lecture-cookie-stale"
        path.mkdir(mode=0o700)
        old = time.time() - 7200
        os.utime(path, (old, old))
        return path

    def symlink(self, target, link, directory=False):
        try:
            os.symlink(target, link, target_is_directory=directory)
        except OSError as error:
            self.skipTest(f"Symlink creation unavailable: {error}")

    def sweep(self):
        with mock.patch.object(cookies.tempfile, "gettempdir", return_value=str(self.root)):
            return cookies._sweep_stale_cookie_copies()


class TestStaleCopyBoundary(IsolatedCase):
    def test_sweep_never_overwrites_a_file_symlink_target(self):
        sentinel = self.root / "sentinel.txt"
        sentinel.write_bytes(b"leave me intact")
        stale = self.stale_dir()
        self.symlink(sentinel, stale / "Cookies")
        old = time.time() - 7200
        os.utime(stale, (old, old))
        self.sweep()
        self.assertEqual(sentinel.read_bytes(), b"leave me intact")

    def test_sweep_never_enters_a_directory_symlink(self):
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "Cookies"
        sentinel.write_bytes(b"leave me intact")
        old = time.time() - 7200
        os.utime(outside, (old, old))
        self.symlink(outside, self.root / "zju-lecture-cookie-link", directory=True)
        self.sweep()
        self.assertTrue(sentinel.exists(), "The sweep must not enter a linked directory")
        self.assertEqual(sentinel.read_bytes(), b"leave me intact")

    def test_sweep_skips_directories_owned_by_another_user(self):
        stale = self.stale_dir()
        sentinel = stale / "Cookies"
        sentinel.write_bytes(b"another user")
        old = time.time() - 7200
        os.utime(stale, (old, old))
        with mock.patch.object(os, "getuid", return_value=stale.stat().st_uid + 1, create=True):
            self.assertEqual(self.sweep(), 0)
        self.assertEqual(sentinel.read_bytes(), b"another user")

    def test_sweep_never_overwrites_hardlinked_files(self):
        sentinel = self.root / "sentinel.txt"
        sentinel.write_bytes(b"leave me intact")
        stale = self.stale_dir()
        os.link(sentinel, stale / "Cookies")
        old = time.time() - 7200
        os.utime(stale, (old, old))
        self.sweep()
        self.assertEqual(sentinel.read_bytes(), b"leave me intact")

    def test_owned_private_stale_copy_is_removed(self):
        stale = self.stale_dir()
        (stale / "Cookies").write_bytes(b"synthetic row")
        old = time.time() - 7200
        os.utime(stale, (old, old))
        self.assertEqual(self.sweep(), 1)
        self.assertFalse(stale.exists())


@unittest.skipUnless(sys.platform == "win32", "Native Windows DPAPI")
class TestNativeCookieDpapi(unittest.TestCase):
    def encrypt(self, plain):
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD),
                        ("pbData", ctypes.POINTER(ctypes.c_char))]

        buf = ctypes.create_string_buffer(plain, len(plain))
        source = Blob(len(plain), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        target = Blob()
        self.assertTrue(ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)
        ))
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(target.pbData)

    def test_valid_native_dpapi_returns_cookie_plaintext(self):
        encrypted = self.encrypt(b"synthetic_cookie_value_123")
        self.assertEqual(cookies._decrypt_win_cookie(encrypted), "synthetic_cookie_value_123")

    def test_versioned_chromium_values_are_not_treated_as_raw_dpapi(self):
        encrypted = self.encrypt(b"synthetic_cookie_value_123")
        for prefix in (b"v10", b"v20"):
            with self.subTest(prefix=prefix):
                self.assertEqual(cookies._decrypt_win_cookie(prefix + encrypted), "")


class TestClearFailure(IsolatedCase):
    def test_failed_keyring_delete_is_reported_and_session_remains(self):
        def runner(argv, stdin_text=None, timeout=10.0):
            if "delete-generic-password" in argv or "clear" in argv:
                return 1, "", "synthetic keyring locked"
            return 0, credential_store.encode_secret(PAYLOAD), ""

        for backend in (credential_store.KeychainBackend(runner),
                        credential_store.SecretToolBackend(runner)):
            with self.subTest(backend=backend.name), mock.patch.object(
                credential_store, "backend", return_value=backend
            ):
                result = browser_login.clear_session()
                self.assertFalse(result["session_removed"])
                self.assertTrue(result["backend_error"])
                self.assertEqual(browser_login.load_session_cookie(), COOKIE)

    @unittest.skipUnless(sys.platform == "win32", "Native Windows file sharing")
    def test_locked_session_file_is_reported_as_not_removed(self):
        from ctypes import wintypes

        path = Path(browser_login.session_file())
        backend = credential_store.DpapiFileBackend(lambda: str(path))
        backend.save(PAYLOAD)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            with mock.patch.object(credential_store, "backend", return_value=backend):
                result = browser_login.clear_session()
            self.assertFalse(result["session_removed"])
            self.assertTrue(result["backend_error"])
            self.assertTrue(path.exists())
        finally:
            kernel.CloseHandle(handle)
        self.assertEqual(backend.load(), PAYLOAD)


class TestPlaintextMigration(IsolatedCase):
    def legacy_file(self):
        path = Path(browser_login.session_file())
        path.parent.mkdir(mode=0o700)
        path.write_bytes(credential_store.LEGACY_BLOB_MAGIC + b"P" + json.dumps(PAYLOAD).encode())
        return path

    def test_failed_dpapi_migration_removes_old_plaintext(self):
        path = self.legacy_file()
        backend = credential_store.DpapiFileBackend(lambda: str(path))
        with mock.patch.object(credential_store, "backend", return_value=backend), \
             mock.patch.object(backend, "save", side_effect=credential_store.StoreUnavailable("synthetic failure")):
            self.assertEqual(browser_login.load_session_cookie(), COOKIE)
        self.assertFalse(path.exists())

    def test_failed_migration_cleanup_propagates_without_returning_credentials(self):
        path = self.legacy_file()
        backend = credential_store.DpapiFileBackend(lambda: str(path))
        with mock.patch.object(credential_store, "backend", return_value=backend), \
             mock.patch.object(backend, "save", side_effect=credential_store.StoreUnavailable("synthetic failure")), \
             mock.patch.object(credential_store, "_secure_remove", return_value=False), \
             mock.patch.object(browser_login, "_secure_remove", return_value=False):
            with self.assertRaises(credential_store.StoreUnavailable) as caught:
                browser_login.load_session_cookie()
        self.assertNotIn(COOKIE, str(caught.exception))
        self.assertTrue(path.exists())

    def test_posix_legacy_cleanup_failure_is_also_reported(self):
        self.legacy_file()
        backend = credential_store.MemoryBackend()
        with mock.patch.object(credential_store, "backend", return_value=backend), \
             mock.patch.object(browser_login, "_secure_remove", return_value=False):
            with self.assertRaises(credential_store.StoreUnavailable):
                browser_login.load_session_cookie()


if __name__ == "__main__":
    unittest.main()
