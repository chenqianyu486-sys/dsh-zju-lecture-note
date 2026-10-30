# -*- coding: utf-8 -*-
"""
Browser cookie helper for extracting ZJU Classroom login sessions.
Supports Microsoft Edge on macOS and Windows using pure standard library.
Also supports cookie string formatting and manual token injection.
"""

import glob
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

DEFAULT_DOMAIN = "classroom.zju.edu.cn"


class CookieAccessError(Exception):
    """Raised when Edge cookies cannot be read.

    ``reason`` distinguishes the failure modes that need different user
    actions: ``locked`` (Edge is running and holds the database lock),
    ``not_found`` (no Edge profile database), ``no_rows`` (not logged in),
    ``decrypt_failed`` (cookie present but unreadable).
    """

    def __init__(self, message: str, hint: str = "", reason: str = "unknown"):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.message}\n{self.hint}" if self.hint else self.message


# --------------------------------------------------------------- Pure Python AES-128-CBC for macOS
_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16"
)
_INV_SBOX = bytes(_SBOX.index(i) for i in range(256))
_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36)


def _xtime(a: int) -> int:
    a <<= 1
    return a ^ 0x1B if a & 0x100 else a


def _gmul(a: int, b: int) -> int:
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        b >>= 1
        a = _xtime(a)
    return p & 0xFF


def _key_expansion(key: bytes):
    w = [list(key[4 * i: 4 * i + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [w[4 * r: 4 * r + 4] for r in range(11)]


def _add_round_key(state, rk):
    for c in range(4):
        for r in range(4):
            state[r][c] ^= rk[c][r]


def _inv_shift_rows(s):
    s[1] = s[1][3:] + s[1][:3]
    s[2] = s[2][2:] + s[2][:2]
    s[3] = s[3][1:] + s[3][:1]


def _inv_mix_columns(s):
    for c in range(4):
        a = s[0][c], s[1][c], s[2][c], s[3][c]
        s[0][c] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
        s[1][c] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
        s[2][c] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
        s[3][c] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)


def _aes128_decrypt_block(block: bytes, round_keys) -> bytes:
    s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
    _add_round_key(s, round_keys[10])
    for rnd in range(9, 0, -1):
        _inv_shift_rows(s)
        s = [[_INV_SBOX[b] for b in row] for row in s]
        _add_round_key(s, round_keys[rnd])
        _inv_mix_columns(s)
    _inv_shift_rows(s)
    s = [[_INV_SBOX[b] for b in row] for row in s]
    _add_round_key(s, round_keys[0])
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _aes128_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    round_keys = _key_expansion(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(ciphertext), 16):
        block = ciphertext[i: i + 16]
        dec = _aes128_decrypt_block(block, round_keys)
        out.extend(b ^ p for b, p in zip(dec, prev))
        prev = block
    pad = out[-1] if out else 0
    if 1 <= pad <= 16 and all(b == pad for b in out[-pad:]):
        return bytes(out[:-pad])
    return bytes(out)


# --------------------------------------------------------------- Platform Readers

def _get_mac_key() -> Optional[bytes]:
    """Derive the macOS Keychain key for Edge's Safe Storage.

    Edge stores the Safe Storage master password in the login keychain; the
    cookie encryption key is PBKDF2-SHA1(password, "saltysalt", 1003, 16).
    """
    # Preferred: ask for the password only (stdout carries it verbatim).
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-w",
             "-s", "Microsoft Edge Safe Storage", "-a", "Microsoft Edge"],
            capture_output=True, text=True, timeout=60,
        )
        pwd = (raw.stdout or "").strip()
        if raw.returncode == 0 and pwd:
            return hashlib.pbkdf2_hmac("sha1", pwd.encode("utf-8"), b"saltysalt", 1003, 16)
    except Exception:
        pass

    # Fallback: the classic "-ga" form prints "password: <value>" on stderr.
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-ga", "Microsoft Edge",
             "-s", "Microsoft Edge Safe Storage"],
            capture_output=True, text=True, timeout=60,
        )
        raw = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    except Exception:
        return None
    for line in raw.splitlines():
        if "password:" in line:
            pwd = line.split("password:", 1)[1].strip()
            if pwd.startswith('"') and pwd.endswith('"'):
                pwd = pwd[1:-1]
            if pwd:
                return hashlib.pbkdf2_hmac("sha1", pwd.encode("utf-8"), b"saltysalt", 1003, 16)
    return None


def _decrypt_mac_cookie(encrypted: bytes, key: bytes) -> str:
    if not encrypted.startswith(b"v10") or len(encrypted) <= 3:
        return ""
    dec = _aes128_cbc_decrypt(encrypted[3:], key, b" " * 16)
    return dec.decode("utf-8", "ignore")


def _dpapi_unprotect(data: bytes) -> bytes:
    """Unprotect a blob with Windows DPAPI. Returns b"" on failure."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        return b""
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


# DPAPI blobs start with a DWORD version (1) followed by the payload length.
_DPAPI_MAGIC = b"\x01\x00\x00\x00"


def _decrypt_win_cookie(encrypted: bytes) -> str:
    """Decrypt a Windows Edge cookie value.

    Chromium stores the value either as a raw DPAPI blob or with a ``v10`` /
    ``v20`` version prefix in front of the DPAPI payload. Both layouts are
    attempted, and the result is validated against the DPAPI blob header so a
    wrong guess cannot silently yield garbage.
    """
    if not encrypted:
        return ""
    candidates = [encrypted]
    if encrypted[:3] in (b"v10", b"v20"):
        candidates.append(encrypted[3:])
    for blob in candidates:
        plain = _dpapi_unprotect(blob)
        if plain.startswith(_DPAPI_MAGIC):
            return plain.decode("utf-8", "ignore")
    return ""


def _edge_root() -> Optional[str]:
    if IS_MAC:
        return os.path.expanduser("~/Library/Application Support/Microsoft Edge")
    if IS_WIN:
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data")
    return None


def _cookie_db_candidates(edge_root: str) -> List[str]:
    """Every Edge profile cookie database, newest layout first."""
    return (
        glob.glob(os.path.join(edge_root, "*", "Network", "Cookies"))
        + glob.glob(os.path.join(edge_root, "*", "Cookies"))
    )


def _copy_cookie_db(db_path: str) -> str:
    """Copy the live Edge cookie DB to a temp file.

    Chromium keeps the database locked while the browser runs, so the file is
    copied out before it is opened. Raises OSError (PermissionError on
    Windows) when the copy is refused.
    """
    handle = tempfile.NamedTemporaryFile(prefix="edge-cookies-", suffix=".db", delete=False)
    tmp_path = handle.name
    handle.close()
    try:
        shutil.copyfile(db_path, tmp_path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path


def read_edge_cookies(
    domain_filter: str = DEFAULT_DOMAIN
) -> Tuple[Optional[str], Optional[CookieAccessError]]:
    """Read Edge cookies for ``domain_filter``.

    Returns ``(cookie_header, error)``. On success ``error`` is None; on
    failure ``cookie_header`` is None and ``error`` carries a message plus an
    actionable hint. The failure modes are deliberately distinguishable: a
    locked database and a missing login look identical if every exception is
    swallowed.
    """
    edge_root = _edge_root()
    if not edge_root:
        return None, CookieAccessError(
            f"当前系统（{sys.platform}）不支持自动读取 Edge Cookie。",
            "请在浏览器开发者工具里复制 Cookie 后手动传入 cookie 参数。",
            reason="unsupported_platform",
        )

    if not os.path.isdir(edge_root):
        return None, CookieAccessError(
            "未找到 Microsoft Edge 的用户数据目录。",
            "请确认本机已安装并登录过 Edge。",
            reason="not_found",
        )

    if IS_MAC:
        key = _get_mac_key()
        if not key:
            return None, CookieAccessError(
                "无法从 macOS 钥匙串读取 Edge 的 Safe Storage 密钥。",
                "首次运行请在弹出的钥匙串授权框中选择『始终允许』；"
                "或改用手动粘贴 Cookie。",
                reason="keychain_denied",
            )
        decrypt_fn = lambda raw: _decrypt_mac_cookie(raw, key)
    else:
        decrypt_fn = _decrypt_win_cookie

    candidates = _cookie_db_candidates(edge_root)
    if not candidates:
        return None, CookieAccessError(
            "未找到 Edge 的 Cookie 数据库。",
            "请确认本机已安装 Edge 并至少登录过一次。",
            reason="not_found",
        )

    locked = False
    db_error: Optional[Exception] = None
    rows: List[Tuple[str, str, str, Optional[bytes]]] = []

    for db_path in candidates:
        try:
            tmp_path = _copy_cookie_db(db_path)
        except PermissionError:
            locked = True
            continue
        except OSError:
            locked = True
            continue
        try:
            conn = sqlite3.connect(tmp_path)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT host_key, name, value, encrypted_value FROM cookies "
                    "WHERE host_key LIKE ?",
                    (f"%{domain_filter}%",),
                )
                rows.extend(cursor.fetchall())
            finally:
                conn.close()
        except sqlite3.Error as exc:
            db_error = exc
            continue
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if rows:
            break

    if not rows:
        if locked:
            return None, CookieAccessError(
                "Edge 正在运行，Cookie 数据库被独占锁定，无法读取。",
                "请完全退出 Edge（包括后台驻留进程）后重试；"
                "或直接在浏览器开发者工具里复制 Cookie 手动传入。",
                reason="locked",
            )
        if db_error is not None:
            return None, CookieAccessError(
                f"读取 Edge Cookie 数据库失败：{db_error}",
                "请完全退出 Edge 后重试。",
                reason="db_error",
            )
        return None, CookieAccessError(
            f"Edge 中没有 {domain_filter} 的 Cookie。",
            "请先在 Edge 中登录智云课堂，然后再读取登录态。",
            reason="no_rows",
        )

    pairs: List[str] = []
    seen = set()
    decrypt_failures = 0
    for _host, name, plain_value, encrypted_value in rows:
        if (name, plain_value) in seen:
            continue
        value = plain_value or ""
        if not value and encrypted_value:
            try:
                value = decrypt_fn(encrypted_value)
            except Exception:
                value = ""
            if not value:
                decrypt_failures += 1
        if not value:
            continue
        seen.add((name, plain_value))
        pairs.append(f"{name}={value}")

    if not pairs:
        return None, CookieAccessError(
            f"读取到 {len(rows)} 条 {domain_filter} 的 Cookie，但全部解密失败。",
            "新版 Edge（v20 应用绑定加密）可能无法用本地权限解密；"
            "请在浏览器开发者工具里复制 Cookie 手动传入。",
            reason="decrypt_failed",
        )

    if decrypt_failures:
        print(
            f"[zju-lecture] {decrypt_failures} 条 Edge Cookie 解密失败，已跳过。",
            file=sys.stderr,
        )

    return "; ".join(pairs), None


def get_edge_cookie(domain_filter: str = DEFAULT_DOMAIN) -> Optional[str]:
    """Backwards-compatible helper: return the cookie header or None."""
    cookie, _error = read_edge_cookies(domain_filter)
    return cookie
