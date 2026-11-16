# -*- coding: utf-8 -*-
"""Encrypted-at-rest session storage for every supported platform.

Design rules
------------

* **No plaintext, ever.** The classroom login cookie is only ever written
  through a platform credential facility: DPAPI on Windows, the login Keychain
  on macOS, Secret Service on Linux. When none of them is available the session
  stays in memory and the caller is told why — re-login is preferred over a
  plaintext file at any location.
* **Secrets never appear on a command line.** ``ps`` shows argv to every local
  user on the machine, so the macOS write path goes through ``security -i``
  (the command, including the secret, arrives on stdin) and the Linux write path
  through ``secret-tool store`` (secret on stdin). Reads and deletes only pass
  metadata (service / account).
* **No hand-rolled cryptography.** A key derived from a passphrase, a machine
  id or a fixed constant protects nothing against another process running as
  the same user, and it advertises "encrypted" while adding no real boundary.
  The only implementations used here are the platform ones.

Honest boundary (also in ``SECURITY.md``): the OS store protects the secret
*at rest* — disk images, backups, other system users, a stolen laptop — and it
keeps it out of the plugin's own files. It does not protect against malware
already running as the same user, because such a process can ask the same store
for the same item.

Backend selection
-----------------

``ZJU_LOGIN_STORAGE=os`` (default) picks the platform backend; ``memory``
refuses to persist at all. A missing/unusable backend degrades to ``memory``
with a reason instead of falling back to a private file: the file *is* the
plaintext path this module exists to remove.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from .cookies import _secure_remove

#: Prefix of the keyring secret. ``[A-Za-z0-9_:-]`` only, so the value can never
#: be split by ``security -i``'s whitespace tokenizer or need quote escaping.
SECRET_PREFIX = "zju-lecture-session-v2:"

#: Legacy on-disk blob (2.2.7 and earlier). Windows wrote ``"D" + DPAPI``,
#: POSIX wrote ``"P" + plaintext``; only the reader keeps the plaintext branch.
LEGACY_BLOB_MAGIC = b"ZJU-LOGIN\x01"

#: DPAPI entropy — **must not change**, otherwise existing Windows sessions
#: become undecryptable.
SESSION_ENTROPY = b"zju-lecture-summarizer-login-v1"

#: The same ceiling the 2.2.7 file format used.
SESSION_MAX_BYTES = 64 * 1024

#: Keychain / Secret Service item identity.
SERVICE = "zju-lecture-classroom"
ACCOUNT = "classroom"

#: ``security -i`` and ``secret-tool`` can block on a locked keyring or a D-Bus
#: that never answers; a credential store must never hang a login or a doctor.
COMMAND_TIMEOUT_SECONDS = 10.0

STORAGE_ENV = "ZJU_LOGIN_STORAGE"
LOGIN_DIR_ENV = "ZJU_LOGIN_DIR"
SESSION_FILE_NAME = "session.bin"

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

Runner = Callable[..., Tuple[int, str, str]]


class StoreUnavailable(Exception):
    """A credential backend exists on paper but cannot be used right now.

    ``reason`` is a short, value-free sentence suitable for a tool result.
    """

    def __init__(self, reason: str, hint: str = "") -> None:
        self.reason = reason
        self.hint = hint
        super().__init__(f"{reason}\n{hint}" if hint else reason)


class StoreCleanupError(StoreUnavailable):
    """Old credential material remains on disk; callers must not hide this."""


# --------------------------------------------------------------------- encoding


def encode_secret(payload: Dict[str, Any]) -> str:
    """Serialise one session payload into the keyring string format."""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > SESSION_MAX_BYTES:
        raise StoreUnavailable("登录态过大，已拒绝保存。")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return SECRET_PREFIX + body


def decode_secret(text: str) -> Optional[Dict[str, Any]]:
    """Parse a keyring string; ``None`` when it is not one of ours."""
    value = str(text or "").strip()
    if not value.startswith(SECRET_PREFIX):
        return None
    body = value[len(SECRET_PREFIX):].strip()
    if not body or any(char.isspace() for char in body):
        return None
    padding = "=" * (-len(body) % 4)
    try:
        raw = base64.urlsafe_b64decode(body + padding)
    except (ValueError, TypeError):
        return None
    if len(raw) > SESSION_MAX_BYTES:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def decode_legacy_blob(blob: bytes) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Decode the 2.2.7 file format into ``(mode, payload)``.

    ``mode`` is ``"D"`` (DPAPI) or ``"P"`` (plaintext). The plaintext branch is
    read-only and exists solely to migrate and delete old files.
    """
    if not blob or not blob.startswith(LEGACY_BLOB_MAGIC):
        return None
    marker = blob[len(LEGACY_BLOB_MAGIC):][:1]
    body = blob[len(LEGACY_BLOB_MAGIC) + 1:]
    if marker == b"D":
        if sys.platform != "win32":
            return None
        try:
            body = _dpapi_unprotect(body)
        except OSError:
            return None
    elif marker != b"P":
        return None
    if not body or len(body) > SESSION_MAX_BYTES:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return marker.decode("ascii"), payload


# ------------------------------------------------------------------------- DPAPI


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Protect/unprotect bytes with Windows DPAPI, bound to the current user."""
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    entropy_buffer = ctypes.create_string_buffer(SESSION_ENTROPY, len(SESSION_ENTROPY))
    entropy_blob = DATA_BLOB(
        len(SESSION_ENTROPY),
        ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_char)),
    )
    blob_out = DATA_BLOB()
    # CRYPTPROTECT_UI_FORBIDDEN: a tool call must never open an OS dialog.
    flags = 0x1
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in), "zju-lecture login", ctypes.byref(entropy_blob),
            None, None, flags, ctypes.byref(blob_out),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, ctypes.byref(entropy_blob),
            None, None, flags, ctypes.byref(blob_out),
        )
    if not ok:
        error = ctypes.get_last_error()
        raise OSError(f"DPAPI 调用失败（错误码 {error}）")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise OSError("DPAPI 只在 Windows 上可用")
    return _dpapi(data, protect=False)


# ----------------------------------------------------------------------- runner


def run_command(
    argv: Sequence[str],
    stdin_text: Optional[str] = None,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
) -> Tuple[int, str, str]:
    """Run one credential-store CLI call with a hard timeout.

    A locked keyring or a half-initialised D-Bus session can block forever, so
    ``TimeoutExpired`` is mapped to :class:`StoreUnavailable` instead of being
    allowed to hang ``zju_doctor`` or the login flow.
    """
    try:
        completed = subprocess.run(
            list(argv),
            input=stdin_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise StoreUnavailable(
            "凭据库响应超时（D-Bus/密钥环可能未解锁或无图形会话）",
            "解锁密钥环后重试；无图形会话的服务器请改用 ZJU_COOKIE_FILE。",
        ) from exc
    except FileNotFoundError as exc:
        raise StoreUnavailable(f"未找到命令 {argv[0]}") from exc
    except OSError as exc:
        raise StoreUnavailable(f"无法调用 {argv[0]}：{exc}") from exc
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


# --------------------------------------------------------------------- locations


def login_dir() -> str:
    """The per-user directory for the login profile and legacy session file."""
    override = str(os.environ.get(LOGIN_DIR_ENV, "") or "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if IS_WIN:
        base = str(os.environ.get("LOCALAPPDATA", "") or "").strip() or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        return os.path.join(base, "zju-lecture")
    if IS_MAC:
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "zju-lecture")
    base = str(os.environ.get("XDG_STATE_HOME", "") or "").strip() or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(base, "zju-lecture")


def session_file() -> str:
    """Path of the Windows DPAPI blob / of a legacy plaintext session file."""
    return os.path.join(login_dir(), SESSION_FILE_NAME)


# ---------------------------------------------------------------------- backends


class SessionBackend:
    """One credential store. ``save`` returns a human-readable descriptor."""

    name = "memory"
    persistent = False

    def describe(self) -> str:
        raise NotImplementedError

    def advice(self) -> str:
        """One actionable sentence when the backend cannot persist."""
        return ""

    def save(self, payload: Dict[str, Any]) -> str:
        raise NotImplementedError

    def load(self) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def clear(self) -> bool:
        return False


def _atomic_write(path: str, data: bytes, mode: int = 0o600) -> None:
    """Write ``data`` to ``path`` through a private temp file + ``os.replace``."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = ""
    try:
        descriptor, temporary = tempfile.mkstemp(
            dir=directory, prefix=".zju-session-", suffix=".tmp"
        )
        if hasattr(os, "fchmod"):
            try:
                os.fchmod(descriptor, mode)
            except OSError:
                pass
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = ""
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


class DpapiFileBackend(SessionBackend):
    """Windows: DPAPI-encrypted file, the 2.2.7 format kept for compatibility."""

    name = "dpapi"
    persistent = True

    def __init__(self, path_provider: Callable[[], str]) -> None:
        self._path_provider = path_provider

    def describe(self) -> str:
        return "Windows DPAPI 加密文件（%LOCALAPPDATA%\\zju-lecture，仅当前用户可解密）"

    def save(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(raw) > SESSION_MAX_BYTES:
            raise StoreUnavailable("登录态过大，已拒绝保存。")
        try:
            blob = LEGACY_BLOB_MAGIC + b"D" + _dpapi(raw, protect=True)
        except OSError as exc:
            raise StoreUnavailable(
                f"DPAPI 加密失败：{exc}",
                "在当前 Windows 用户下重试；仍失败可改用 ZJU_COOKIE_FILE。",
            ) from exc
        try:
            _atomic_write(self._path_provider(), blob)
        except OSError as exc:
            raise StoreUnavailable(
                f"写入登录态文件失败：{exc}",
                "检查用户目录写权限，或设置 ZJU_LOGIN_DIR。",
            ) from exc
        return self.describe()

    def load(self) -> Optional[Dict[str, Any]]:
        path = self._path_provider()
        try:
            if not os.path.isfile(path) or os.path.getsize(path) > SESSION_MAX_BYTES + 1024:
                return None
            with open(path, "rb") as handle:
                blob = handle.read()
        except OSError:
            return None
        decoded = decode_legacy_blob(blob)
        if not decoded:
            return None
        mode, payload = decoded
        if mode == "P":
            # A plaintext blob on Windows (e.g. copied from a POSIX machine)
            # is rewritten through DPAPI in place.
            try:
                self.save(payload)
            except StoreUnavailable as exc:
                # Keep the current call usable, but never retain the old
                # plaintext merely because the encrypted replacement failed.
                if not _secure_remove(path) and os.path.lexists(path):
                    raise StoreCleanupError(
                        "旧明文登录态未能迁移，也未能删除。",
                        "关闭占用 session.bin 的程序并检查文件权限，再调用 zju_login(clear=true) 清理。",
                    ) from exc
        return payload

    def clear(self) -> bool:
        path = self._path_provider()
        if not os.path.lexists(path):
            return False
        if not _secure_remove(path) and os.path.lexists(path):
            raise StoreCleanupError(
                "本地登录态文件未能删除（可能被占用或没有写权限）。",
                "关闭占用 session.bin 的程序并检查权限后重试清除。",
            )
        return True


def _security_failure(code: int, stdout: str, stderr: str) -> str:
    """Turn a ``security`` result into a failure sentence (``""`` when fine)."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith("security>")]
    if code == 45:
        return "钥匙串中已有同名项且未能更新（exit 45）"
    if code != 0:
        detail = lines[0] if lines else "无错误输出"
        return f"security 命令失败（exit {code}）：{detail}"
    if lines:
        # Some macOS builds print the failure to stderr yet still exit 0; the
        # read-back check in ``save`` is the authoritative guard, this is the
        # fast path for an obviously broken call.
        return f"security 报告错误（返回码 0）：{lines[0]}"
    return ""


class KeychainBackend(SessionBackend):
    """macOS: a generic-password item in the login Keychain."""

    name = "keychain"
    persistent = True

    def __init__(self, runner: Runner = run_command) -> None:
        self._run = runner

    def describe(self) -> str:
        return "macOS 钥匙串（Keychain，静态加密）"

    def save(self, payload: Dict[str, Any]) -> str:
        secret = encode_secret(payload)
        # The payload charset is [A-Za-z0-9_:-]; refuse anything else rather than
        # letting ``security -i`` split or mangle it.
        if any(char.isspace() for char in secret):
            raise StoreUnavailable("凭据含空白字符，已拒绝写入钥匙串。")
        command = (
            f"add-generic-password -U -s {SERVICE} -a {ACCOUNT} "
            f"-l {SERVICE} -w {secret}"
        )
        code, out, err = self._run(
            [_which("security") or "security", "-i"],
            stdin_text=command + "\n",
        )
        problem = _security_failure(code, out, err)
        if problem:
            raise StoreUnavailable(problem, "调用 zju_login 重试；仍失败可改用 ZJU_COOKIE_FILE。")
        if self.load() != payload:
            self.clear()
            raise StoreUnavailable(
                "钥匙串写入后回读不一致，已删除该凭据项。",
                "重试一次；仍失败请检查钥匙串是否已解锁。",
            )
        return self.describe()

    def load(self) -> Optional[Dict[str, Any]]:
        code, out, err = self._run(
            [_which("security") or "security", "find-generic-password", "-w",
             "-s", SERVICE, "-a", ACCOUNT]
        )
        if code == 44:  # errSecItemNotFound
            return None
        problem = _security_failure(code, out, err)
        if problem:
            raise StoreUnavailable(problem)
        return decode_secret(out)

    def clear(self) -> bool:
        code, out, err = self._run(
            [_which("security") or "security", "delete-generic-password",
             "-s", SERVICE, "-a", ACCOUNT]
        )
        if code == 44:
            return False
        problem = _security_failure(code, out, err)
        if problem:
            raise StoreUnavailable(problem, "解锁系统钥匙串后重试清除。")
        return True


class SecretToolBackend(SessionBackend):
    """Linux: Secret Service item written through ``secret-tool``."""

    name = "secret-service"
    persistent = True

    def __init__(self, runner: Runner = run_command) -> None:
        self._run = runner

    def describe(self) -> str:
        return "Linux 密钥环（Secret Service，静态加密）"

    def save(self, payload: Dict[str, Any]) -> str:
        secret = encode_secret(payload)
        code, _out, err = self._run(
            ["secret-tool", "store", "--label", SERVICE,
             "service", SERVICE, "account", ACCOUNT],
            stdin_text=secret,
        )
        if code != 0:
            detail = (err or "").strip().splitlines()
            raise StoreUnavailable(
                "写入密钥环失败：" + (detail[0] if detail else f"exit {code}"),
                "确认密钥环已解锁；无桌面会话请改用 ZJU_COOKIE_FILE。",
            )
        if self.load() != payload:
            self.clear()
            raise StoreUnavailable(
                "密钥环写入后回读不一致，已删除该凭据项。",
                "重试一次；仍失败可改用 ZJU_COOKIE_FILE。",
            )
        return self.describe()

    def load(self) -> Optional[Dict[str, Any]]:
        code, out, err = self._run(
            ["secret-tool", "lookup", "service", SERVICE, "account", ACCOUNT]
        )
        if code == 0:
            return decode_secret(out)
        if (err or "").strip():
            raise StoreUnavailable(
                "读取密钥环失败：" + err.strip().splitlines()[0],
                "确认 D-Bus 会话与密钥环可用；无桌面会话请改用 ZJU_COOKIE_FILE。",
            )
        return None

    def clear(self) -> bool:
        code, _out, err = self._run(
            ["secret-tool", "clear", "service", SERVICE, "account", ACCOUNT]
        )
        if code == 1 and not err.strip():
            return False
        if code != 0:
            detail = err.strip().splitlines()
            raise StoreUnavailable(
                "清除密钥环失败：" + (detail[0] if detail else f"exit {code}"),
                "解锁系统密钥环后重试清除。",
            )
        return code == 0


class MemoryBackend(SessionBackend):
    """No persistence at all: the session lives for this process only."""

    name = "memory"
    persistent = False

    def __init__(self, reason: str = "") -> None:
        self._payload: Optional[Dict[str, Any]] = None
        self._reason = reason

    def describe(self) -> str:
        detail = f"（{self._reason}）" if self._reason else ""
        return f"仅内存，不落盘{detail}"

    def advice(self) -> str:
        return (
            "仅当前进程有效（CLI 单次命令退出即失效；"
            "无桌面/无密钥环环境建议用 ZJU_COOKIE_FILE 自行管理登录态）。"
        )

    def save(self, payload: Dict[str, Any]) -> str:
        self._payload = dict(payload)
        return self.describe()

    def load(self) -> Optional[Dict[str, Any]]:
        return dict(self._payload) if self._payload else None

    def clear(self) -> bool:
        had = self._payload is not None
        self._payload = None
        return had


# ------------------------------------------------------------------- selection


def storage_mode() -> str:
    """``os`` (persist through the platform store) or ``memory`` (never persist)."""
    raw = str(os.environ.get(STORAGE_ENV, "") or "").strip().lower()
    return "memory" if raw in ("memory", "none", "off") else "os"


def default_backend(
    platform: Optional[str] = None,
    session_path: Optional[Callable[[], str]] = None,
    runner: Runner = run_command,
) -> SessionBackend:
    """Pick the backend for ``platform`` without ever falling back to a file."""
    system = platform or sys.platform
    if storage_mode() == "memory":
        return MemoryBackend("ZJU_LOGIN_STORAGE=memory")
    if system == "win32":
        return DpapiFileBackend(session_path or session_file)
    if system == "darwin":
        if _which("security"):
            return KeychainBackend(runner)
        return MemoryBackend("未找到 macOS security 命令")
    if system.startswith("linux"):
        if _which("secret-tool"):
            return SecretToolBackend(runner)
        return MemoryBackend(
            "未找到 secret-tool（安装 libsecret-tools 后可持久化）"
        )
    return MemoryBackend(f"当前平台（{system}）没有可用的加密凭据库")


_BACKEND: Optional[SessionBackend] = None
_BACKEND_KEY: Optional[Tuple[str, str, str]] = None


def session_path_from(login_dir: Callable[[], str], filename: str = "session.bin") -> Callable[[], str]:
    """Lazily resolve ``<login dir>/<filename>`` (the env can change per test)."""
    return lambda: os.path.join(login_dir(), filename)


def backend() -> SessionBackend:
    """The process-wide backend, rebuilt when the environment changes."""
    global _BACKEND, _BACKEND_KEY
    key = (
        storage_mode(),
        os.environ.get("ZJU_LOGIN_DIR", ""),
        sys.platform,
    )
    if _BACKEND is None or key != _BACKEND_KEY:
        _BACKEND = default_backend()
        _BACKEND_KEY = key
    return _BACKEND


def reset_backend() -> None:
    """Forget the cached backend (tests, or after ``zju_login(clear=true)``)."""
    global _BACKEND, _BACKEND_KEY
    _BACKEND = None
    _BACKEND_KEY = None
