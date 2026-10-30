# -*- coding: utf-8 -*-
"""Privacy helpers shared by the MCP server, the CLI and the dsh plugin.

Two guarantees live here:

* **Secrets never leave the process.** Every login cookie that the server
  reads is registered with :class:`SecretRedactor`; all model-facing output,
  JSON-RPC responses and stderr diagnostics pass through it, so a cookie
  cannot be echoed by accident (a traceback, a debug print, a new tool).
* **Local file access stays inside the courseware/notes envelope.** The
  extractor and the note linter are the only tools that touch local files, and
  a model can name any path. :func:`guard_local_file` rejects credential
  stores, browser databases and key material before they are ever read, so a
  prompt injection cannot turn "extract my slides" into "read the cookie jar".

Everything is standard library only.
"""

import os
import re
from typing import Iterable, List, Optional

# --------------------------------------------------------------------------- secrets

REDACTED = "[REDACTED]"

# A short value would redact ordinary prose; cookie values are longer than this.
_MIN_SECRET_LENGTH = 4


class SecretRedactor:
    """Replace every registered secret with ``[REDACTED]`` in outbound text.

    The redactor keeps only the values it is told about (the cookie header and
    each individual cookie value), never their origin: it is a last line of
    defence for output paths that were not written with cookies in mind.
    """

    def __init__(self) -> None:
        self._secrets: List[str] = []

    def add(self, value: Optional[str]) -> None:
        """Register one secret. Empty/short values are ignored."""
        if not isinstance(value, str):
            return
        text = value.strip()
        if len(text) < _MIN_SECRET_LENGTH:
            return
        if text not in self._secrets:
            self._secrets.append(text)

    def add_cookie(self, cookie_header: Optional[str]) -> None:
        """Register a full ``Cookie:`` header plus each ``name=value`` value."""
        if not cookie_header:
            return
        self.add(cookie_header)
        for part in cookie_header.split(";"):
            part = part.strip()
            if "=" in part:
                self.add(part.split("=", 1)[1].strip())

    def redact(self, text: object) -> str:
        """Return ``text`` with every registered secret masked."""
        if text is None:
            return ""
        rendered = text if isinstance(text, str) else str(text)
        # Longest first so a header is masked as a whole before its values.
        for secret in sorted(self._secrets, key=len, reverse=True):
            if secret in rendered:
                rendered = rendered.replace(secret, REDACTED)
        return rendered

    def clear(self) -> None:
        """Forget all registered secrets (used by tests)."""
        self._secrets.clear()

    def __bool__(self) -> bool:
        return bool(self._secrets)


#: Process-wide redactor. ``mcp_server`` populates it when a cookie is read.
REDACTOR = SecretRedactor()


# --------------------------------------------------------------------------- cookies

MAX_COOKIE_LENGTH = 8192

# ``Cookie:`` prefix in all its spellings; users paste it together with the
# header name often enough that accepting it is kinder than a validation error.
_COOKIE_PREFIX_RE = re.compile(r"^\s*cookie\s*:\s*", re.IGNORECASE)


def sanitize_cookie_header(raw: str) -> str:
    """Validate and normalise a pasted/env/file cookie header.

    The result is safe to put in an HTTP header: no CR/LF (header injection),
    no empty pair names, bounded length, one canonical ``name=value; ...``
    spelling.

    Raises:
        ValueError: with a message that never contains the cookie value.
    """
    if raw is None:
        raise ValueError("Cookie 为空")
    text = _COOKIE_PREFIX_RE.sub("", str(raw).strip())
    if not text:
        raise ValueError("Cookie 为空")
    if "\r" in text or "\n" in text:
        raise ValueError("Cookie 含换行符，已拒绝（防止 HTTP 头注入）")
    if len(text) > MAX_COOKIE_LENGTH:
        raise ValueError(f"Cookie 长度超过 {MAX_COOKIE_LENGTH} 字符，已拒绝")

    pairs: List[str] = []
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError("Cookie 必须是 name=value 形式")
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            raise ValueError("Cookie 存在空的 name")
        pairs.append(f"{name}={value}")
    if not pairs:
        raise ValueError("Cookie 为空")
    return "; ".join(pairs)


def cookie_names(cookie_header: str) -> List[str]:
    """Return the cookie names (never values) for a diagnostic summary."""
    names: List[str] = []
    for part in (cookie_header or "").split(";"):
        name = part.split("=", 1)[0].strip()
        if name:
            names.append(name)
    return names


def describe_cookie(cookie_header: str) -> dict:
    """A value-free description of a cookie header, safe to echo."""
    names = cookie_names(cookie_header)
    return {
        "cookie_count": len(names),
        "cookie_names": names,
        "total_length": len(cookie_header or ""),
    }


def mask_cookie_header(cookie_header: str) -> str:
    """``name=***`` rendering for human-facing CLI output."""
    masked = []
    for part in (cookie_header or "").split(";"):
        part = part.strip()
        if not part:
            continue
        name = part.split("=", 1)[0].strip()
        if name:
            masked.append(f"{name}=***")
    return "; ".join(masked)


# --------------------------------------------------------------------------- local files

MAX_LOCAL_FILE_BYTES = 16 * 1024 * 1024

COURSEWARE_EXTENSIONS = frozenset({
    ".pptx", ".docx", ".pdf", ".txt", ".md", ".markdown", ".csv", ".json",
})
NOTE_EXTENSIONS = frozenset({".md", ".markdown"})

# Directory components that hold credentials or browser profile state. A file
# below one of these is refused before it is opened, however it is named.
# (`AppData` itself is deliberately absent: Windows temp directories live
# below it, and the concrete browser/credential folders are matched by name
# and file patterns instead.)
_SENSITIVE_DIRS = frozenset({
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".dsh", ".minimax",
    ".config", ".gnome2", ".pki", "credentials",
})

# File names that are almost always credentials, key material or browser
# state. Matched against the lower-cased basename.
_SENSITIVE_NAME_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"^\.env($|\.)",
    r"credential", r"secret", r"password", r"passwd", r"apikey", r"api[_-]key",
    r"private", r"token", r"cookie", r"login data", r"web data",
    r"^history$", r"^history\.(txt|db)$",
    r"^config\.json$", r"^\.netrc$", r"^\.npmrc$", r"^\.pypirc$",
    r"^\.git-credentials$", r"^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$",
    r"^known_hosts$",
    r"\.(pem|key|p12|pfx|kdbx|db|sqlite|sqlite3|ovpn|ppk|crt|der|jks|keystore)$",
))

# Explicit opt-out for a user who really means to point the tool at one of
# these files. Documented in SECURITY.md and never enabled by the plugin.
ALLOW_SENSITIVE_ENV = "ZJU_ALLOW_SENSITIVE_PATHS"


class LocalFileError(Exception):
    """Raised when a local path is outside the courseware/notes envelope."""


def _sensitive_reason(real_path: str) -> Optional[str]:
    """Return why ``real_path`` looks sensitive, or ``None`` when it is fine."""
    normalised = real_path.replace("\\", "/").lower()
    parts = [part for part in normalised.split("/") if part and not part.endswith(":")]
    for part in parts:
        if part in _SENSITIVE_DIRS:
            return "敏感目录"
    basename = parts[-1] if parts else ""
    for pattern in _SENSITIVE_NAME_PATTERNS:
        if pattern.search(basename):
            return "敏感文件名"
    return None


def guard_local_file(
    path: str,
    allowed_extensions: Iterable[str],
    kind: str = "文件",
) -> str:
    """Validate a model-supplied local path and return its canonical form.

    Checks, in order: non-empty input, existence, regular file, size cap,
    extension allow-list, and the credential/browser-data heuristic. The
    returned path is ``realpath``-resolved so a symlink cannot smuggle a
    blocked target past the name check.

    Raises:
        LocalFileError: with a user-facing, content-free explanation.
    """
    if not isinstance(path, str) or not path.strip():
        raise LocalFileError(f"{kind}路径不能为空")

    expanded = os.path.expanduser(path.strip())
    try:
        real_path = os.path.realpath(expanded)
    except OSError as exc:
        raise LocalFileError(f"无法解析{kind}路径: {exc}") from exc

    if not os.path.exists(real_path):
        raise LocalFileError(f"找不到{kind}: {expanded}")
    if not os.path.isfile(real_path):
        raise LocalFileError(f"{kind}路径不是普通文件: {expanded}")

    try:
        size = os.path.getsize(real_path)
    except OSError as exc:
        raise LocalFileError(f"无法读取{kind}信息: {exc}") from exc
    if size > MAX_LOCAL_FILE_BYTES:
        raise LocalFileError(
            f"{kind}超过 {MAX_LOCAL_FILE_BYTES // (1024 * 1024)} MiB 上限，已拒绝读取"
        )

    extension = os.path.splitext(real_path)[1].lower()
    allowed = {item.lower() for item in allowed_extensions}
    if extension not in allowed:
        raise LocalFileError(
            f"不支持的{kind}格式 '{extension or '(无扩展名)'}'，"
            f"只允许: {', '.join(sorted(allowed))}"
        )

    reason = _sensitive_reason(real_path)
    if reason and os.environ.get(ALLOW_SENSITIVE_ENV) != "1":
        raise LocalFileError(
            f"出于隐私保护，拒绝读取{reason}的文件（{os.path.basename(real_path)}）。"
            "本工具只处理课件与讲义；如确有必要，请设置环境变量 "
            f"{ALLOW_SENSITIVE_ENV}=1 后重试。"
        )

    return real_path
