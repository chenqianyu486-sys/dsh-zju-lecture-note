# -*- coding: utf-8 -*-
"""One-click ZJU Classroom login through a dedicated browser profile.

Why this exists
---------------

Recent Edge builds enable App-Bound Encryption (ABE) for cookies. Once ABE is
on, an external process cannot decrypt the cookie database even after Edge is
closed, so the old "read Edge cookies" path dead-ends and the user is asked to
open DevTools and copy a cookie by hand. That is unacceptable for non-technical
users.

This module opens a **separate** browser profile, navigates to the classroom,
and asks the browser process itself for its cookies through the Chrome DevTools
Protocol (CDP). ABE never enters the picture, the user's daily Edge profile is
never touched, and the login page handles SSO / 2FA normally.

The cookie header is then stored securely:

* Windows: DPAPI (``CryptProtectData``), decryptable only by the same Windows
  user on this machine;
* macOS / Linux: a ``0600`` file under the user's state directory.

No password is ever accepted or stored. The only inputs are a classroom URL,
a timeout and a ``clear`` flag.

Everything is standard library only. The browser is expected to be Edge
(preferred) or Chrome / Chromium on Windows, macOS and Linux.
"""

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .client import extract_classroom_token, is_zju_host
from .cookies import DEFAULT_DOMAIN, _host_matches, _parent_domain, _secure_remove
from .security import cookie_names, sanitize_cookie_header

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

DEFAULT_LOGIN_URL = "https://classroom.zju.edu.cn/"
LOGIN_DIR_ENV = "ZJU_LOGIN_DIR"
BROWSER_ENV = "ZJU_BROWSER_BIN"

SESSION_MAGIC = b"ZJU-LOGIN\x01"
SESSION_VERSION = 1
SESSION_MAX_BYTES = 64 * 1024
SESSION_ENTROPY = b"zju-lecture-summarizer-login-v1"
PROFILE_DIR_NAME = "login-profile"
SESSION_FILE_NAME = "session.bin"

MAX_LOGIN_TIMEOUT = 540
MIN_LOGIN_TIMEOUT = 30
DEVTOOLS_START_TIMEOUT = 30.0


class LoginError(Exception):
    """A login-window failure with one actionable next step.

    ``reason`` is machine-readable so the MCP layer can print one conclusion
    instead of a list of maybes: ``no_browser`` / ``bad_url`` / ``launch_failed``
    / ``devtools_blocked`` / ``closed`` / ``timeout`` / ``save_failed``.
    """

    def __init__(self, message: str, hint: str = "", reason: str = "unknown"):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.message}\n{self.hint}" if self.hint else self.message


# ------------------------------------------------------------------ locations

def login_dir() -> str:
    """The per-user directory for the login profile and the saved session."""
    override = os.environ.get(LOGIN_DIR_ENV, "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA", "").strip() or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        return os.path.join(base, "zju-lecture")
    if IS_MAC:
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "zju-lecture")
    base = os.environ.get("XDG_STATE_HOME", "").strip() or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(base, "zju-lecture")


def profile_dir() -> str:
    return os.path.join(login_dir(), PROFILE_DIR_NAME)


def session_file() -> str:
    return os.path.join(login_dir(), SESSION_FILE_NAME)


def _ensure_private_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


# ------------------------------------------------------------------ browsers

def browser_candidates() -> List[str]:
    """Existing browser executables, Edge first, then Chrome / Chromium."""
    explicit = os.environ.get(BROWSER_ENV, "").strip()
    if explicit:
        expanded = os.path.abspath(os.path.expanduser(explicit))
        return [expanded] if os.path.isfile(expanded) else []

    candidates: List[str] = []
    if IS_WIN:
        bases = [
            os.environ.get(name, "").strip()
            for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
        ]
        bases = [base for base in bases if base]
        # Edge first across every install root, then Chrome. Mixing the two
        # inside each root made Chrome win whenever Edge lived in Program
        # Files (x86) and Chrome in Program Files.
        candidates.extend(
            os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            for base in bases
        )
        candidates.extend(
            os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            for base in bases
        )
    elif IS_MAC:
        candidates.extend([
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            os.path.join(os.path.expanduser("~"), "Applications", "Microsoft Edge.app",
                         "Contents", "MacOS", "Microsoft Edge"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.join(os.path.expanduser("~"), "Applications", "Google Chrome.app",
                         "Contents", "MacOS", "Google Chrome"),
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])
    else:
        for name in (
            "microsoft-edge-stable", "microsoft-edge", "google-chrome-stable",
            "google-chrome", "chromium", "chromium-browser",
        ):
            found = shutil.which(name)
            if found:
                candidates.append(found)

    seen = set()
    result = []
    for path in candidates:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        if os.path.isfile(path):
            result.append(os.path.abspath(path))
    return result


def find_browser() -> Optional[str]:
    candidates = browser_candidates()
    return candidates[0] if candidates else None


def browser_label(path: Optional[str]) -> str:
    name = os.path.basename(path or "")
    lowered = name.lower()
    if "msedge" in lowered or "edge" in lowered:
        return "Microsoft Edge"
    if "chrome" in lowered:
        return "Google Chrome"
    if "chromium" in lowered:
        return "Chromium"
    return name or "浏览器"


def login_available() -> Tuple[bool, str]:
    """``(available, detail)`` for diagnostics; never touches a credential."""
    path = find_browser()
    if not path:
        return False, "未找到 Edge / Chrome / Chromium"
    return True, f"{browser_label(path)}（{path}）"


# ------------------------------------------------------------------ DPAPI (Windows)

def _win_dpapi(data: bytes, protect: bool, entropy: bytes) -> bytes:
    """Protect/unprotect bytes with Windows DPAPI, bound to the current user."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    entropy_buf = None
    entropy_blob = None
    if entropy:
        entropy_buf = ctypes.create_string_buffer(entropy, len(entropy))
        entropy_blob = DATA_BLOB(
            len(entropy), ctypes.cast(entropy_buf, ctypes.POINTER(ctypes.c_char))
        )
    p_entropy = ctypes.byref(entropy_blob) if entropy_blob is not None else None
    # CRYPTPROTECT_UI_FORBIDDEN: never show an OS prompt from a tool call.
    flags = 0x1
    try:
        if protect:
            ok = crypt32.CryptProtectData(
                ctypes.byref(blob_in), "zju-lecture login", p_entropy,
                None, None, flags, ctypes.byref(blob_out),
            )
        else:
            ok = crypt32.CryptUnprotectData(
                ctypes.byref(blob_in), None, p_entropy,
                None, None, flags, ctypes.byref(blob_out),
            )
    except OSError as exc:
        raise LoginError(
            f"Windows DPAPI 调用失败：{exc}",
            "请在当前 Windows 用户下重试；若仍失败，可改用 ZJU_COOKIE_FILE。",
            reason="save_failed",
        ) from exc
    if not ok:
        error = ctypes.get_last_error()
        raise LoginError(
            f"Windows DPAPI 调用失败（错误码 {error}）。",
            "请确认当前 Windows 用户有可用的用户配置；也可改用 ZJU_COOKIE_FILE。",
            reason="save_failed",
        )
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _encode_session(payload: Dict[str, Any]) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(raw) > SESSION_MAX_BYTES:
        raise LoginError("登录态过大，已拒绝保存。", reason="save_failed")
    if IS_WIN:
        return SESSION_MAGIC + b"D" + _win_dpapi(raw, True, SESSION_ENTROPY)
    return SESSION_MAGIC + b"P" + raw


def _decode_session(blob: bytes) -> Optional[Dict[str, Any]]:
    if not blob.startswith(SESSION_MAGIC):
        return None
    mode = blob[len(SESSION_MAGIC): len(SESSION_MAGIC) + 1]
    body = blob[len(SESSION_MAGIC) + 1:]
    if mode == b"D":
        if not IS_WIN:
            return None
        try:
            body = _win_dpapi(body, False, SESSION_ENTROPY)
        except LoginError:
            return None
    elif mode != b"P":
        return None
    if len(body) > SESSION_MAX_BYTES:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def save_session(cookie: str, browser: str = "") -> str:
    """Validate + persist the cookie header; return the file path."""
    try:
        header = sanitize_cookie_header(cookie)
    except ValueError as exc:
        raise LoginError(
            f"浏览器返回的登录态格式不合法：{exc}",
            "请重试登录；若仍失败，改用 ZJU_COOKIE_FILE。",
            reason="save_failed",
        ) from exc
    if not extract_classroom_token(header):
        raise LoginError(
            "登录态里没有 _token，无法用于字幕鉴权。",
            "请确认登录的是 classroom.zju.edu.cn（不是其他浙大站点），然后重试。",
            reason="save_failed",
        )
    payload = {
        "version": SESSION_VERSION,
        "saved_at": int(time.time()),
        "browser": browser,
        "cookie": header,
    }
    blob = _encode_session(payload)
    directory = login_dir()
    target = session_file()
    tmp = ""
    try:
        _ensure_private_dir(directory)
        # mkstemp 用 O_EXCL 建文件，固定 ".tmp" 路径可被预置的链接劫持。
        descriptor, tmp = tempfile.mkstemp(
            dir=directory, prefix=".zju-session-", suffix=".tmp"
        )
        # Create with 0600 from the first byte on POSIX; Windows ignores the
        # mode and relies on DPAPI plus the per-user profile directory.
        if hasattr(os, "fchmod"):
            try:
                os.fchmod(descriptor, 0o600)
            except OSError:
                pass
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        tmp = ""
    except OSError as exc:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise LoginError(
            f"登录成功，但保存登录态失败：{exc}",
            "本次会话仍可使用；请检查用户目录写权限，或改用 ZJU_COOKIE_FILE。",
            reason="save_failed",
        ) from exc
    return target


def _read_session_payload() -> Optional[Dict[str, Any]]:
    path = session_file()
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > SESSION_MAX_BYTES + 1024:
            return None
        with open(path, "rb") as handle:
            payload = _decode_session(handle.read())
    except OSError:
        return None
    if not payload or payload.get("version") != SESSION_VERSION:
        return None
    return payload


def load_session_cookie() -> Optional[str]:
    """Return the saved cookie header, or ``None`` when absent/invalid."""
    payload = _read_session_payload()
    if not payload:
        return None
    raw = payload.get("cookie")
    if not isinstance(raw, str):
        return None
    try:
        header = sanitize_cookie_header(raw)
    except ValueError:
        return None
    return header if extract_classroom_token(header) else None


def session_summary() -> Dict[str, Any]:
    """Credential-free description of the saved session (safe for diagnostics)."""
    payload = _read_session_payload()
    if not payload:
        return {"available": False, "path": session_file()}
    raw = payload.get("cookie")
    if not isinstance(raw, str):
        return {"available": False, "path": session_file()}
    try:
        header = sanitize_cookie_header(raw)
    except ValueError:
        return {"available": False, "path": session_file()}
    names = cookie_names(header)
    return {
        "available": bool(extract_classroom_token(header)),
        "path": session_file(),
        "saved_at": payload.get("saved_at"),
        "browser": payload.get("browser") or "",
        "cookie_count": len(names),
        "names": names,
        "has_token": bool(extract_classroom_token(header)),
    }


def clear_session(delete_profile: bool = True) -> Dict[str, Any]:
    """Delete the saved session and (optionally) the dedicated browser profile."""
    removed_session = os.path.exists(session_file())
    if removed_session:
        _secure_remove(session_file())
    removed_profile = False
    profile_error = ""
    if delete_profile:
        profile = profile_dir()
        # Only ever delete our own directory; never follow a symlink out of it.
        expected = os.path.join(login_dir(), PROFILE_DIR_NAME)
        if os.path.normcase(os.path.abspath(profile)) == os.path.normcase(os.path.abspath(expected)):
            real = os.path.realpath(profile)
            is_link = os.path.normcase(real) != os.path.normcase(os.path.abspath(profile))
            if is_link:
                # Never follow a symlink/junction outside our state directory.
                try:
                    os.rmdir(profile)
                except OSError:
                    try:
                        os.unlink(profile)
                    except OSError as exc:
                        profile_error = str(exc)
                        removed_profile = False
                    else:
                        removed_profile = True
                else:
                    removed_profile = True
            elif os.path.isdir(profile):
                try:
                    shutil.rmtree(profile)
                    removed_profile = True
                except OSError as exc:
                    profile_error = str(exc)
    try:
        os.rmdir(login_dir())
    except OSError:
        pass
    return {
        "session_removed": removed_session,
        "profile_removed": removed_profile,
        "profile_error": profile_error,
        "profile_path": profile_dir(),
    }


# ------------------------------------------------------------------ CDP transport

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class _WSClosed(Exception):
    pass


class _WebSocket:
    """A minimal RFC 6455 client, enough for local CDP text frames."""

    def __init__(self, url: str, timeout: float = 10.0):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "ws" or not parsed.hostname:
            raise LoginError("浏览器调试端口地址不合法。", reason="devtools_blocked")
        host = parsed.hostname
        port = parsed.port or 80
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._buffer = bytearray()
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(request.encode("ascii"))
        self._read_handshake(key)

    def _read_handshake(self, key: str) -> None:
        header = bytearray()
        while b"\r\n\r\n" not in header:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise LoginError("浏览器在调试握手时关闭了连接。", reason="devtools_blocked")
            header.extend(chunk)
            if len(header) > 65536:
                raise LoginError("浏览器调试握手响应异常。", reason="devtools_blocked")
        head, _, rest = bytes(header).partition(b"\r\n\r\n")
        self._buffer.extend(rest)
        lines = head.split(b"\r\n")
        if not lines or b" 101 " not in lines[0]:
            raise LoginError("浏览器拒绝本机调试连接。", reason="devtools_blocked")
        headers = {}
        for line in lines[1:]:
            name, separator, value = line.partition(b":")
            if separator:
                headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
        )
        if headers.get(b"sec-websocket-accept") != expected:
            raise LoginError("浏览器调试握手校验失败。", reason="devtools_blocked")

    def _read_exact(self, size: int, deadline: float) -> bytes:
        while len(self._buffer) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout("websocket read timed out")
            self._sock.settimeout(remaining)
            chunk = self._sock.recv(65536)
            if not chunk:
                raise _WSClosed()
            self._buffer.extend(chunk)
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    def _send_frame(self, opcode: int, payload: bytes = b"") -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def recv_text(self, deadline: float) -> str:
        fragments: List[bytes] = []
        while True:
            first, second = self._read_exact(2, deadline)
            finished = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2, deadline))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8, deadline))[0]
            if length > 8 * 1024 * 1024:
                raise LoginError("浏览器调试消息过大。", reason="devtools_blocked")
            mask = self._read_exact(4, deadline) if masked else b""
            payload = self._read_exact(length, deadline)
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                raise _WSClosed()
            if opcode == 0x1:
                fragments = [payload]
            elif opcode == 0x0:
                fragments.append(payload)
            else:
                continue
            if finished:
                return b"".join(fragments).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self._send_frame(0x8)
        except Exception:
            pass
        try:
            self._sock.close()
        except OSError:
            pass


class _Cdp:
    def __init__(self, ws_url: str, timeout: float = 10.0):
        self._ws = _WebSocket(ws_url, timeout)
        self._next_id = 0

    def call(self, method: str, params: Optional[Dict[str, Any]] = None,
             timeout: float = 10.0) -> Dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._ws.send_text(json.dumps({
            "id": request_id,
            "method": method,
            "params": params or {},
        }))
        deadline = time.monotonic() + timeout
        while True:
            try:
                message = json.loads(self._ws.recv_text(deadline))
            except socket.timeout as exc:
                raise LoginError(
                    f"等待浏览器响应超时（{method}）。",
                    "请重试；若反复超时，检查安全软件是否拦截了本机调试端口。",
                    reason="devtools_blocked",
                ) from exc
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            if message.get("error"):
                error = message["error"]
                detail = error.get("message") if isinstance(error, dict) else str(error)
                raise LoginError(
                    f"浏览器调试命令失败（{method}）：{detail}",
                    "请重试登录；若仍失败，改用 ZJU_COOKIE_FILE。",
                    reason="devtools_blocked",
                )
            return message.get("result") or {}

    def close(self) -> None:
        self._ws.close()


def _local_json(url: str, timeout: float = 2.0) -> Dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _read_active_port(profile: str) -> Optional[Tuple[int, str]]:
    path = os.path.join(profile, "DevToolsActivePort")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    if not lines:
        return None
    try:
        port = int(lines[0].strip())
    except (TypeError, ValueError):
        return None
    if not port:
        return None
    return port, (lines[1].strip() if len(lines) > 1 else "")


def _probe_endpoint(profile: str) -> Optional[str]:
    """Return a browser websocket URL from a live DevToolsActivePort."""
    active = _read_active_port(profile)
    if not active:
        return None
    port, path = active
    if path:
        ws_url = f"ws://127.0.0.1:{port}{path}"
        try:
            version = _local_json(f"http://127.0.0.1:{port}/json/version", timeout=1.0)
        except Exception:
            return None
        product = str(version.get("Browser") or "")
        if "Edg" not in product and "Chrome" not in product and "Chromium" not in product:
            return None
        return ws_url
    try:
        version = _local_json(f"http://127.0.0.1:{port}/json/version", timeout=1.0)
    except Exception:
        return None
    value = str(version.get("webSocketDebuggerUrl") or "")
    return value if value.startswith("ws://127.0.0.1:") else None


def _wait_endpoint(profile: str, process: Optional[subprocess.Popen],
                   timeout: float = DEVTOOLS_START_TIMEOUT) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        endpoint = _probe_endpoint(profile)
        if endpoint:
            return endpoint
        if process is not None and process.poll() is not None:
            # Give the port file a last chance: a forwarded instance can exit
            # before the new one has finished writing.
            time.sleep(0.3)
            endpoint = _probe_endpoint(profile)
            if endpoint:
                return endpoint
            raise LoginError(
                "浏览器启动后立即退出。可能是独立登录窗口已在运行，或浏览器被策略禁止使用调试端口。",
                "请关闭本插件打开的独立登录窗口后重试；仍不行就改用 ZJU_COOKIE_FILE 高级兜底。",
                reason="launch_failed",
            )
        time.sleep(0.3)
    raise LoginError(
        "浏览器没有开放本机调试端口。",
        "可能是企业策略禁用了远程调试，或被安全软件拦截。"
        "请稍后重试；仍不行就改用 ZJU_COOKIE_FILE 高级兜底。",
        reason="devtools_blocked",
    )


# ------------------------------------------------------------------ cookies

def _cookie_header_from_cdp(cookies: List[Dict[str, Any]]) -> str:
    """Keep exactly the cookies a browser would send to the classroom host.

    Classroom-host cookies come first; domain-scoped ``.zju.edu.cn`` cookies
    (where the PHP-serialized ``_token`` lives) come second. Host-only cookies
    of other ZJU subdomains are excluded. Duplicate names keep the first row,
    matching ``read_edge_cookies``.
    """
    parent = _parent_domain(DEFAULT_DOMAIN) or "zju.edu.cn"
    rows: List[Tuple[int, str, str]] = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "")
        domain = str(cookie.get("domain") or "").strip()
        if not name or not value:
            continue
        expires = cookie.get("expires")
        if isinstance(expires, (int, float)) and 0 < expires < time.time():
            continue
        if _host_matches(domain, DEFAULT_DOMAIN):
            tier = 0
        elif domain.lower().lstrip(".") == parent.lower() and domain.startswith("."):
            tier = 1
        else:
            continue
        rows.append((tier, name, value))
    rows.sort(key=lambda item: item[0])
    seen = set()
    pairs: List[str] = []
    for _tier, name, value in rows:
        if name in seen:
            continue
        seen.add(name)
        pairs.append(f"{name}={value}")
    if not pairs:
        return ""
    try:
        return sanitize_cookie_header("; ".join(pairs))
    except ValueError:
        return ""


def _get_cookies(cdp: _Cdp) -> List[Dict[str, Any]]:
    try:
        result = cdp.call("Storage.getCookies", timeout=8.0)
    except LoginError:
        result = cdp.call("Network.getAllCookies", timeout=8.0)
    value = result.get("cookies")
    return value if isinstance(value, list) else []


# ------------------------------------------------------------------ login window

def sanitize_login_url(value: str) -> str:
    """Only allow an https URL on ``*.zju.edu.cn`` (never a lookalike)."""
    url = (value or "").strip()
    if not url:
        return DEFAULT_LOGIN_URL
    if len(url) > 2048:
        raise LoginError("登录链接过长。", reason="bad_url")
    if url.startswith("//"):
        url = "https:" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.username or parsed.password:
        raise LoginError("登录链接不能包含用户名或密码。", reason="bad_url")
    if parsed.scheme == "http" and is_zju_host(parsed.hostname):
        url = "https" + url[4:]
        parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not is_zju_host(parsed.hostname):
        raise LoginError(
            "登录窗口只允许打开 https 的浙大域名（*.zju.edu.cn）。",
            "请传这节课的智云课堂链接，例如 https://classroom.zju.edu.cn/livingroom?...",
            reason="bad_url",
        )
    return url


def _launch_browser(binary: str, profile: str, url: str) -> subprocess.Popen:
    args = [
        binary,
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--remote-debugging-port=0",
        "--remote-debugging-address=127.0.0.1",
        "--start-maximized",
        url,
    ]
    kwargs: Dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if IS_WIN:
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        return subprocess.Popen(args, **kwargs)
    except OSError as exc:
        raise LoginError(
            f"无法启动浏览器：{exc}",
            "请确认 Edge / Chrome 可正常打开；也可设置 ZJU_BROWSER_BIN 指向浏览器可执行文件。",
            reason="launch_failed",
        ) from exc


def _close_browser(cdp: Optional[_Cdp], process: Optional[subprocess.Popen]) -> None:
    if cdp is not None:
        try:
            cdp.call("Browser.close", timeout=3.0)
        except Exception:
            pass
        cdp.close()
    if process is not None:
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass


def open_login_window(url: str = "", timeout_s: int = 300) -> Dict[str, Any]:
    """Open the dedicated login window and wait for a classroom ``_token``.

    Returns a credential-free summary plus the cookie header for the caller's
    in-process cache. The cookie is *never* printed by this module.
    """
    target = sanitize_login_url(url)
    try:
        timeout = int(timeout_s)
    except (TypeError, ValueError):
        timeout = 300
    timeout = max(MIN_LOGIN_TIMEOUT, min(timeout, MAX_LOGIN_TIMEOUT))

    binary = find_browser()
    if not binary:
        raise LoginError(
            "未找到可用的浏览器（Edge / Chrome / Chromium）。",
            "请先安装 Microsoft Edge 或 Google Chrome；无图形界面的服务器请改用 ZJU_COOKIE_FILE。",
            reason="no_browser",
        )

    profile = profile_dir()
    try:
        _ensure_private_dir(profile)
    except OSError as exc:
        raise LoginError(
            f"无法创建独立登录配置目录：{exc}",
            "请检查用户状态目录的写权限，或设置 ZJU_LOGIN_DIR 指向可写目录；"
            "无图形界面的服务器改用 ZJU_COOKIE_FILE。",
            reason="launch_failed",
        ) from exc
    started = time.monotonic()
    process: Optional[subprocess.Popen] = None
    cdp: Optional[_Cdp] = None
    try:
        # Always start a fresh instance. Reusing a stale DevToolsActivePort
        # could connect to an unrelated browser that reused the same port;
        # if an old login window is still open, the new launch forwards to it
        # and exits, and the error tells the user to close it.
        try:
            os.unlink(os.path.join(profile, "DevToolsActivePort"))
        except OSError:
            pass
        process = _launch_browser(binary, profile, target)
        endpoint = _wait_endpoint(profile, process)
        try:
            cdp = _Cdp(endpoint, timeout=10.0)
        except (OSError, _WSClosed) as exc:
            raise LoginError(
                f"无法连接浏览器的本机调试端口：{exc}",
                "请重试；若仍失败，可能是安全软件或企业策略拦截了本机调试。",
                reason="devtools_blocked",
            ) from exc
        deadline = time.monotonic() + timeout
        while True:
            try:
                cookies = _get_cookies(cdp)
            except (OSError, _WSClosed):
                raise LoginError(
                    "登录窗口已被关闭，没有检测到完整登录态。",
                    "请重新调用 zju_login，并在新窗口里完成登录后再关闭窗口。",
                    reason="closed",
                )
            header = _cookie_header_from_cdp(cookies)
            if header and extract_classroom_token(header):
                saved_path = ""
                save_error = ""
                try:
                    saved_path = save_session(header, browser=browser_label(binary))
                except LoginError as exc:
                    save_error = exc.message
                return {
                    "cookie": header,
                    "names": cookie_names(header),
                    "browser": browser_label(binary),
                    "elapsed": round(time.monotonic() - started, 1),
                    "saved": bool(saved_path),
                    "saved_path": saved_path,
                    "save_error": save_error,
                }
            if process is not None and process.poll() is not None:
                raise LoginError(
                    "登录窗口已退出，没有检测到完整登录态。",
                    "请重新调用 zju_login，并完成登录。",
                    reason="closed",
                )
            if time.monotonic() >= deadline:
                raise LoginError(
                    f"等待 {timeout} 秒仍未检测到登录完成。",
                    "请重新调用 zju_login；登录时不要关闭窗口，成功后窗口会自动关闭。",
                    reason="timeout",
                )
            time.sleep(1.0)
    finally:
        _close_browser(cdp, process)
