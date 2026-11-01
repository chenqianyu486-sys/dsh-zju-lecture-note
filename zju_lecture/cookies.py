# -*- coding: utf-8 -*-
"""
Browser cookie helper for extracting ZJU Classroom login sessions.
Supports Microsoft Edge on macOS and Windows using pure standard library.
Also supports cookie string formatting and manual token injection.
"""

import glob
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import List, Optional, Tuple

from .security import sanitize_cookie_header

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


def _edge_app_bound_enabled() -> bool:
    """Whether Edge uses app-bound encryption for new cookies.

    Edge 127+ can encrypt cookies with a key bound to the application
    (``app_bound_encrypted_key`` in ``Local State``). Such values cannot be
    decrypted by an external process even with DPAPI, so "quit Edge and retry"
    can never work; the user has to supply ``ZJU_COOKIE_FILE`` instead.
    """
    root = _edge_root()
    if not root:
        return False
    try:
        with open(os.path.join(root, "Local State"), "r", encoding="utf-8") as handle:
            state = json.load(handle)
        return bool(state.get("os_crypt", {}).get("app_bound_encrypted_key"))
    except (OSError, ValueError):
        return False


def _cookie_db_candidates(edge_root: str) -> List[str]:
    """Every Edge profile cookie database, newest layout first."""
    return (
        glob.glob(os.path.join(edge_root, "*", "Network", "Cookies"))
        + glob.glob(os.path.join(edge_root, "*", "Cookies"))
    )


def _host_matches(host_key: str, domain: str) -> bool:
    """Exact-or-subdomain match, never a substring match.

    ``LIKE '%classroom.zju.edu.cn%'`` would also match
    ``classroom.zju.edu.cn.attacker.example``; only the real host and its
    subdomains may contribute a login cookie.
    """
    host = (host_key or "").strip().lower().lstrip(".")
    wanted = (domain or "").strip().lower().lstrip(".")
    if not host or not wanted:
        return False
    return host == wanted or host.endswith("." + wanted)


class _DirectReadUnavailable(Exception):
    """The live database could not be opened read-only; copy it first."""


def _parent_domain(domain: str) -> Optional[str]:
    """Return the registrable parent domain for a ZJU host.

    ``classroom.zju.edu.cn`` -> ``zju.edu.cn``. The classroom ``_token``
    lives in a session cookie set on ``.zju.edu.cn`` (the browser sends it to
    every ZJU subdomain), so reading only the classroom host would silently
    fetch a cookie jar without the token.
    """
    labels = [part for part in (domain or "").strip().lower().lstrip(".").split(".") if part]
    if len(labels) < 3:
        return None
    # Public-suffix aware enough for ZJU: .edu.cn registrable domains have
    # three labels (zju.edu.cn), unlike .com with two.
    if labels[-2:] == ["edu", "cn"]:
        if len(labels) == 3:
            return None  # already the registrable domain
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _query_cookie_rows(
    db_path: str,
    domain: str,
    parent_domain: Optional[str] = None,
) -> List[Tuple[str, str, str, Optional[bytes]]]:
    """Query the ``cookies`` table without modifying the database.

    The file is opened read-only, so reading a live Edge database does not
    create a temporary copy at all whenever Chromium allows shared reads.

    ``parent_domain`` adds **domain-scoped** cookies of the parent
    (``host_key = '.zju.edu.cn'``). Host-only cookies of other ZJU
    subdomains are deliberately excluded: a browser would not send those to
    the classroom host either.
    """
    try:
        target = pathlib.Path(db_path).as_uri() + "?mode=ro"
    except ValueError as exc:  # pragma: no cover - malformed path
        raise _DirectReadUnavailable(str(exc)) from exc

    try:
        conn = sqlite3.connect(target, uri=True, timeout=2.0)
    except sqlite3.Error as exc:
        raise _DirectReadUnavailable(str(exc)) from exc
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT host_key, name, value, encrypted_value FROM cookies WHERE host_key LIKE ?",
            (f"%{domain}%",),
        )
        rows = [row for row in cursor.fetchall() if _host_matches(str(row[0]), domain)]
        if parent_domain:
            cursor.execute(
                "SELECT host_key, name, value, encrypted_value FROM cookies WHERE host_key = ?",
                (f".{parent_domain}",),
            )
            rows.extend(cursor.fetchall())
        return rows
    except sqlite3.Error as exc:
        raise _DirectReadUnavailable(str(exc)) from exc
    finally:
        conn.close()


def _secure_remove(path: str) -> None:
    """Overwrite then delete a temporary file that held browser cookies."""
    try:
        with open(path, "r+b") as handle:
            length = handle.seek(0, os.SEEK_END)
            handle.seek(0)
            if length:
                handle.write(b"\0" * length)
                handle.flush()
                os.fsync(handle.fileno())
    except OSError:
        pass
    try:
        os.unlink(path)
    except OSError:
        pass


def _secure_remove_tree(tmp_dir: str) -> None:
    """Shred every file copied into a private temp dir, then remove the dir."""
    try:
        names = os.listdir(tmp_dir)
    except OSError:
        return
    for name in names:
        _secure_remove(os.path.join(tmp_dir, name))
    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass


def _copy_cookie_db(db_path: str) -> str:
    """Copy the live Edge cookie DB and its WAL sidecars into a private dir.

    Chromium keeps the cookie database in WAL mode, so a login issued moments
    ago may still live in ``Cookies-wal`` instead of ``Cookies``. Copying only
    the main file yields an empty table and a misleading "not logged in"
    error. The sidecars are copied too and the copy is opened read-write once,
    which lets SQLite replay and checkpoint the WAL in *our* private copy; the
    browser's own files are never touched.
    """
    tmp_dir = tempfile.mkdtemp(prefix="zju-lecture-cookie-")
    try:
        os.chmod(tmp_dir, 0o700)
    except OSError:
        pass
    tmp_path = os.path.join(tmp_dir, "Cookies")
    try:
        shutil.copyfile(db_path, tmp_path)
        for suffix in ("-wal", "-shm"):
            source = db_path + suffix
            if os.path.exists(source):
                shutil.copyfile(source, tmp_path + suffix)
        for path in (tmp_path, tmp_path + "-wal", tmp_path + "-shm"):
            if os.path.exists(path):
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
        # Read-write open: SQLite replays the copied WAL and checkpoints it.
        conn = sqlite3.connect(tmp_path, timeout=2.0)
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as exc:
        _secure_remove_tree(tmp_dir)
        raise OSError(f"copying the cookie database failed: {exc}") from exc
    return tmp_path


def _read_rows_with_copy(
    db_path: str,
    domain: str,
    parent_domain: Optional[str] = None,
) -> List[Tuple[str, str, str, Optional[bytes]]]:
    """Fallback path: copy the database and WAL, read it, then shred the copy."""
    tmp_path = _copy_cookie_db(db_path)
    try:
        return _query_cookie_rows(tmp_path, domain, parent_domain)
    finally:
        _secure_remove_tree(os.path.dirname(tmp_path))


def read_edge_cookies(
    domain_filter: str = DEFAULT_DOMAIN,
    include_parent: bool = True,
) -> Tuple[Optional[str], Optional[CookieAccessError]]:
    """Read Edge cookies for ``domain_filter``.

    Returns ``(cookie_header, error)``. On success ``error`` is None; on
    failure ``cookie_header`` is None and ``error`` carries a message plus an
    actionable hint. The failure modes are deliberately distinguishable: a
    locked database and a missing login look identical if every exception is
    swallowed.

    Only cookies whose host is exactly ``domain_filter`` or one of its
    subdomains are returned. With ``include_parent`` (default), domain-scoped
    cookies of the parent (``.zju.edu.cn``) are appended too: the classroom
    ``_token`` lives there, and a browser sends it to the classroom host.
    Host-only cookies of unrelated subdomains are never included.
    """
    domain = (domain_filter or "").strip()
    if not domain:
        return None, CookieAccessError(
            "未提供要读取的域名。",
            f"本插件只读取 {DEFAULT_DOMAIN} 的登录态。",
            reason="no_domain",
        )
    parent = _parent_domain(domain) if include_parent else None
    parent_note = f" 或其父域 {parent}" if parent else ""

    edge_root = _edge_root()
    if not edge_root:
        return None, CookieAccessError(
            f"当前系统（{sys.platform}）不支持自动读取 Edge Cookie。",
            "请在宿主配置里设置 ZJU_COOKIE 环境变量（不要把 Cookie 粘贴到对话里）。",
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
                "或在宿主配置里设置 ZJU_COOKIE 环境变量。",
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
            rows = _query_cookie_rows(db_path, domain, parent)
        except _DirectReadUnavailable:
            try:
                rows = _read_rows_with_copy(db_path, domain, parent)
            except OSError:
                locked = True
                continue
            except (_DirectReadUnavailable, sqlite3.Error) as exc:
                db_error = exc
                continue
        if rows:
            break

    if not rows:
        abe = _edge_app_bound_enabled()
        if locked:
            if abe:
                # ABE makes "quit Edge and retry" dead advice: the v20 key is
                # wrapped to the browser process, so quitting Edge removes the
                # lock but never makes the cookie readable outside Edge. Say
                # the one action that actually works, and only that one.
                return None, CookieAccessError(
                    "Edge 正在运行且启用了应用绑定加密（ABE），Cookie 无法在浏览器外部解密。",
                    "退出 Edge 对 ABE 无效：请在宿主配置里设置 ZJU_COOKIE_FILE 环境变量"
                    "（文件内只放一行 Cookie 头，不要粘贴到对话里）。",
                    reason="abe",
                )
            return None, CookieAccessError(
                "Edge 正在运行，Cookie 数据库被独占锁定，无法读取。",
                "请完全退出 Edge（包括后台驻留进程）后重试；"
                "或在宿主配置里设置 ZJU_COOKIE / ZJU_COOKIE_FILE 环境变量"
                "（不要把 Cookie 粘贴到对话里）。",
                reason="locked",
            )
        if db_error is not None:
            if abe:
                return None, CookieAccessError(
                    f"读取 Edge Cookie 数据库失败：{db_error}",
                    "本机 Edge 启用了应用绑定加密（ABE），即使退出 Edge 也无法在浏览器外解密；"
                    "请改用 ZJU_COOKIE_FILE 环境变量（文件内只放一行 Cookie 头）。",
                    reason="abe",
                )
            return None, CookieAccessError(
                f"读取 Edge Cookie 数据库失败：{db_error}",
                "请完全退出 Edge 后重试，或在宿主配置里设置 ZJU_COOKIE_FILE 环境变量"
                "（不要把 Cookie 粘贴到对话里）。",
                reason="db_error",
            )
        return None, CookieAccessError(
            f"Edge 中没有 {domain}{parent_note} 的 Cookie。",
            "请先在 Edge 中登录智云课堂，然后再读取登录态。",
            reason="no_rows",
        )

    pairs: List[str] = []
    seen_names = set()
    decrypt_failures = 0
    for _host, name, plain_value, encrypted_value in rows:
        # Classroom-specific rows come first; keep that one when a parent
        # domain sets a cookie with the same name.
        if name in seen_names:
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
        seen_names.add(name)
        pairs.append(f"{name}={value}")

    if not pairs:
        if _edge_app_bound_enabled():
            hint = (
                "本机 Edge 启用了应用绑定加密（ABE）：新版 v20 Cookie 无法被外部进程解密。"
                "请改用 ZJU_COOKIE_FILE 环境变量（文件内只放一行 Cookie 头），"
                "或在宿主配置里设置 ZJU_COOKIE。"
            )
        else:
            hint = (
                "Cookie 可能是新版 v20 加密格式，无法用本地权限解密；"
                "请在宿主配置里设置 ZJU_COOKIE_FILE 或 ZJU_COOKIE 环境变量。"
            )
        return None, CookieAccessError(
            f"读取到 {len(rows)} 条 {domain}{parent_note} 的 Cookie，但全部解密失败。",
            hint,
            reason="decrypt_failed",
        )

    if decrypt_failures:
        print(
            f"[zju-lecture] {decrypt_failures} 条 Edge Cookie 解密失败，已跳过。",
            file=sys.stderr,
        )

    try:
        return sanitize_cookie_header("; ".join(pairs)), None
    except ValueError as exc:
        return None, CookieAccessError(
            f"Edge 中的 Cookie 格式不合法：{exc}",
            "已拒绝发送该 Cookie。请退出 Edge 后重新登录智云课堂再试。",
            reason="invalid",
        )


def get_edge_cookie(domain_filter: str = DEFAULT_DOMAIN) -> Optional[str]:
    """Backwards-compatible helper: return the cookie header or None."""
    cookie, _error = read_edge_cookies(domain_filter)
    return cookie
