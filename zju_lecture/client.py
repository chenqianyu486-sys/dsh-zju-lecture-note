# -*- coding: utf-8 -*-
"""
Client for Zhejiang University 智云课堂 (classroom.zju.edu.cn) and the
interactive-classroom backend (interactivemeta.cmc.zju.edu.cn) APIs.
Pure Python standard library implementation with zero external dependencies.
"""

import http.client
import ipaddress
import json
import os
import random
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .security import REDACTOR, sanitize_cookie_header

BASE_URL = "https://classroom.zju.edu.cn"
#: 互动式课堂回放与备用 API 后端；回放链接形如
#: ``https://interactivemeta.cmc.zju.edu.cn/#/replay?course_id=...&sub_id=...``。
INTERACTIVE_BASE_URL = "https://interactivemeta.cmc.zju.edu.cn"
BASE_HOST = (urllib.parse.urlparse(BASE_URL).hostname or "classroom.zju.edu.cn").lower()
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


_CA_SOURCE = "system"
_CA_PATH: Optional[str] = None


def _certifi_ca_path() -> Optional[str]:
    """Location of certifi's bundle, when certifi is installed and readable."""
    try:
        import certifi  # type: ignore

        path = certifi.where()
    except Exception:  # noqa: BLE001 - a broken certifi must not crash the tool
        return None
    return path if path and os.path.isfile(path) else None


def _bundled_ca_path() -> Optional[str]:
    """The CA bundle shipped inside this package (``zju_lecture/cacert.pem``).

    dsh ships its own Python interpreter **without** certifi, and a plain
    ``ssl.create_default_context()`` on an incomplete OS root store raises
    ``CERTIFICATE_VERIFY_FAILED``. Carrying our own bundle means the common case
    (dsh on a fresh machine) stops depending on what the user happened to pip
    install.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cacert.pem")
    return path if os.path.isfile(path) else None


def _context_from_cafile(path: str) -> Optional[ssl.SSLContext]:
    """Build a verifying context from ``path``; ``None`` when it is unusable."""
    try:
        return ssl.create_default_context(cafile=path)
    except (OSError, ssl.SSLError):
        return None


def create_ssl_context() -> ssl.SSLContext:
    """Create the TLS context used for every request.

    Certificate verification is **never** disabled. The login cookie is sent
    over this connection, so silently downgrading to an unverified context
    (as an earlier version did when the local root store was incomplete) would
    turn a missing CA bundle into a cookie-exfiltration path.

    Trust store order: ``certifi``（跟得上 CA 轮换）→ 随包 ``cacert.pem``
    （dsh 自带 Python 没有 certifi 时的兜底）→ 系统根证书。三档都失败才会
    在握手上报错，且错误信息里会写清用的是哪一档。
    """
    global _CA_SOURCE, _CA_PATH

    for source, resolver in (("certifi", _certifi_ca_path), ("bundled", _bundled_ca_path)):
        path = resolver()
        if not path:
            continue
        context = _context_from_cafile(path)
        if context is not None:
            _CA_SOURCE, _CA_PATH = source, path
            return context
    _CA_SOURCE, _CA_PATH = "system", None
    return ssl.create_default_context()


_SSL_CONTEXT: Optional[ssl.SSLContext] = None


def get_ssl_context() -> ssl.SSLContext:
    """Return the shared SSL context, building it on first use."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = create_ssl_context()
    return _SSL_CONTEXT


def ssl_context_health() -> Dict[str, Any]:
    """Report the trust store actually in use (for actionable error messages)."""
    try:
        ca_count = len(get_ssl_context().get_ca_certs())
    except Exception:  # noqa: BLE001 - diagnostics must never mask the real error
        ca_count = -1
    return {"source": _CA_SOURCE, "path": _CA_PATH, "ca_certs": ca_count}


def _mask_proxy_credentials(value: str) -> str:
    """Hide ``user:password@`` in a proxy URL before it reaches an error message."""
    return re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+@", r"\1[REDACTED]@", value)


def _proxy_env() -> str:
    """Describe the proxy environment, naming the variables to inspect.

    "未设置" on its own does not tell the user which variable to look at, so the
    unset case spells the names out. Returns a phrase without brackets: the
    callers already wrap it in （）. Proxy userinfo is masked.
    """
    found = []
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(key)
        if value:
            found.append(f"{key}={_mask_proxy_credentials(value)}")
    if found:
        return "，".join(found)
    return "HTTPS_PROXY / HTTP_PROXY 均未设置"


def describe_network_error(error: BaseException) -> str:
    """Turn a transport exception into ``原因 + 下一步``.

    The tool used to surface the raw ``<urlopen error ...>`` text, which made an
    incomplete CA store look like "the plugin's request is broken". 证书校验失败、
    代理拦截、超时、连接被拒这四类占了网络失败的大头，各自给出可执行的下一步。
    """
    text = str(error)
    # urllib 把真实原因包一层 URLError（URLError(reason=SSLCertVerificationError(...))），
    # 不拆包的话「证书校验失败」这条分支永远命中不了。
    inner = getattr(error, "reason", None)
    if isinstance(error, urllib.error.URLError) and isinstance(inner, BaseException):
        text = f"{error} {inner}"
        error = inner
    context = ssl_context_health()
    store = {
        "certifi": "certifi",
        "bundled": "插件内置 cacert.pem",
        "system": "系统根证书",
    }.get(context["source"], "系统根证书")
    if context["path"]:
        store = f"{store} ({context['path']})"

    if isinstance(error, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in text:
        lines = [
            "原因：TLS 证书校验不通过（接口本身没挂，不要用关闭校验的方式绕过——登录 Cookie 走这条连接）。",
            f"信任库：{store}，已加载 {context['ca_certs']} 张 CA 证书；代理环境：{_proxy_env()}。",
        ]
        if context["ca_certs"] == 0:
            lines.append(
                "1. 已加载 0 张证书 → 连随包 CA 都没读到，安装包可能不完整："
                "重装插件；或 `pip install certifi` 后重试。"
            )
        else:
            lines.append(
                "1. 信任库里没有能验证该站点的根证书：`pip install --upgrade certifi`，"
                "或重装插件取回最新内置 cacert.pem。"
            )
        lines += [
            "2. 代理若做 HTTPS 解密（Clash / Surge / 企业网关），把 classroom.zju.edu.cn 设为直连，"
            "或设置 `NO_PROXY=classroom.zju.edu.cn`。",
            "3. 系统时间偏差过大会直接导致握手失败，核对一下系统时间。",
        ]
        return "\n".join(lines)

    if isinstance(error, (socket.timeout, TimeoutError)):
        return f"原因：请求超时（{_proxy_env()}）。可稍后重试；若代理不可用，先关掉代理或设置 NO_PROXY。"
    if isinstance(error, ConnectionRefusedError) or "Connection refused" in text or "10061" in text:
        return f"原因：连接被拒绝，代理很可能没启动（{_proxy_env()}）。"
    if isinstance(error, ssl.SSLEOFError) or "EOF occurred in violation of protocol" in text:
        return f"原因：TLS 握手被中断（{_proxy_env()}），通常是代理/网关拦截，建议重试或改直连。"
    return f"原因：{text}（代理环境：{_proxy_env()}）。"


_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.5


def _is_transient(error: BaseException) -> bool:
    """Classify a transport failure as worth retrying."""
    if isinstance(error, ssl.SSLCertVerificationError):
        return False  # 证书问题重试多少次都一样，立刻把诊断交出去
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500 or error.code == 429
    if isinstance(error, urllib.error.URLError):
        return _is_transient(error.reason)
    return isinstance(
        error,
        (socket.timeout, TimeoutError, ConnectionError, ssl.SSLError, http.client.HTTPException),
    )


def _fetch_bytes(
    url: str,
    headers: Dict[str, str],
    timeout: int,
    attempts: int = _RETRY_ATTEMPTS,
    max_bytes: Optional[int] = None,
    allow_cross_host_redirect: bool = False,
    diagnostics: Optional[List[str]] = None,
) -> bytes:
    """GET ``url`` and read the **whole** body, retrying transient failures.

    The retry has to cover ``read()``, not just the handshake. ``urllib`` builds the
    TLS connection lazily on first use and the body arrives afterwards, so a flaky
    proxy can走完 TCP 握手之后才在读取阶段丢包，表现为
    ``IncompleteRead(201704 bytes read)`` / ``EOF occurred in violation of protocol``。
    只重试建连的话，这类失败仍然一次就穿透到用户面前。

    Certification failures are *not* retried: they need a fix, not a rerun.
    ``max_bytes`` refuses oversized bodies (slide screenshots) before they are
    materialised in memory.
    """
    total = max(1, attempts)
    last: Optional[BaseException] = None
    for index in range(total):
        try:
            if allow_cross_host_redirect:
                context = _open_request(
                    url,
                    headers,
                    timeout,
                    allow_cross_host_redirect=True,
                    diagnostics=diagnostics,
                )
            else:
                context = _open_request(url, headers, timeout)
            with context as response:
                if max_bytes is None:
                    return response.read()
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ZJUAPIError(
                        f"响应超过 {max_bytes // (1024 * 1024)} MiB 上限，已停止读取"
                    )
                return data
        except Exception as error:  # noqa: BLE001 - re-raised below unless transient
            if not _is_transient(error):
                raise
            last = error
            if index + 1 < total:
                time.sleep(_RETRY_BASE_DELAY * (2**index) + random.uniform(0, 0.25))
    assert last is not None
    raise last


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> Tuple[str, str, int]:
    """``(scheme, host, port)`` with default ports filled in.

    hostname+scheme is not enough: ``https://a:443`` and ``https://a:8443`` are
    different origins, and credentials must not cross that boundary.
    """
    parsed = urllib.parse.urlparse(url or "")
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is None:
        port = _DEFAULT_PORTS.get(scheme, 0)
    return scheme, host, port


def _is_forbidden_redirect_host(host: str) -> bool:
    """IP literals, loopback and private names are never valid redirect targets."""
    value = (host or "").strip().lower().rstrip(".")
    if not value:
        return True
    if value == "localhost" or value.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    # Any IP literal (loopback, link-local, RFC1918, ::1, ...) is refused:
    # a media CDN never needs one, and a redirect to one is the classic SSRF.
    return True


def _redirect_block_reason(old_url: str, new_url: str) -> str:
    """Why a redirect must not be followed, or an empty string to allow it."""
    old_scheme, _, _ = _origin(old_url)
    new_scheme, new_host, new_port = _origin(new_url)
    parsed = urllib.parse.urlparse(new_url or "")
    if parsed.username or parsed.password:
        return "已阻止跳转到含凭据的 URL（保护登录态）"
    if old_scheme == "https" and new_scheme != "https":
        return "已阻止 HTTPS 降级重定向（保护登录凭据）"
    if new_scheme not in ("http", "https"):
        return f"已阻止跳转到非 HTTP(S) 地址: {new_scheme or '(无协议)'}"
    if _is_forbidden_redirect_host(new_host):
        return f"已阻止跳转到受限主机: {new_host or '(未知主机)'}"
    return ""


class _SameHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only on the **same origin as the request**.

    ``urllib`` re-sends request headers on a redirect, so a compromised or
    misconfigured endpoint that answers ``302`` to another origin would leak
    the ``Cookie`` / ``Authorization`` headers. This is used for both the
    primary classroom host and the interactive-classroom backend; scheme, host
    and port must all match the request — a downgrade to HTTP or a different
    port is refused as well.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        reason = _redirect_block_reason(req.full_url, newurl)
        if not reason and _origin(newurl) != _origin(req.full_url):
            reason = f"拒绝跨域重定向到 {_origin(newurl)[1] or '(未知主机)'}（保护登录凭据）"
        if reason:
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                reason,
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _StripAuthOnCrossHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allow slide-CDN redirects, but never carry credentials across origins.

    Slide screenshots are static files and may redirect to a ZJU media host or
    an official image CDN. Only those targets are followed (one hop at a time,
    re-validated by urllib for every hop); everything else is blocked and
    recorded. Whenever the redirect changes scheme/host/port, ``Cookie`` /
    ``Authorization`` / ``Proxy-Authorization`` are dropped.
    """

    def __init__(self, diagnostics: Optional[List[str]] = None) -> None:
        super().__init__()
        self.diagnostics = diagnostics

    def _blocked(self, reason: str) -> None:
        if self.diagnostics is not None:
            self.diagnostics.append(reason)

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        reason = _redirect_block_reason(req.full_url, newurl)
        if not reason:
            _, new_host, _ = _origin(newurl)
            if not is_allowed_image_host(new_host):
                reason = (
                    "已阻止跳转到非浙大域/非官方图片 CDN: "
                    f"{new_host or '(未知主机)'}"
                )
        if reason:
            self._blocked(reason)
            return None
        new_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_request is None:
            return None
        if _origin(req.full_url) != _origin(newurl):
            for header in ("Cookie", "Authorization", "Proxy-Authorization"):
                new_request.remove_header(header)
        return new_request


def _open_request(
    url: str,
    headers: Dict[str, str],
    timeout: int,
    allow_cross_host_redirect: bool = False,
    diagnostics: Optional[List[str]] = None,
):
    """Open ``url`` with certificate verification and a redirect policy."""
    redirect_handler = (
        _StripAuthOnCrossHostRedirectHandler(diagnostics)
        if allow_cross_host_redirect
        else _SameHostRedirectHandler()
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=get_ssl_context()),
        redirect_handler,
    )
    request = urllib.request.Request(url, headers=headers)
    return opener.open(request, timeout=timeout)


class ZJUAPIError(Exception):
    """Raised when an API call to ZJU Classroom fails."""
    pass


class TranscriptAuthError(ZJUAPIError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"字幕接口返回 HTTP {status}，当前请求未获访问许可。")


def _fragment_query(fragment: str) -> Dict[str, List[str]]:
    """Parse the query part of a hash-route fragment.

    The interactive classroom page uses ``#/replay?course_id=...&sub_id=...``;
    ``urllib.parse.urlparse`` puts everything after ``#`` in ``fragment``, so a
    normal ``parse_qs(parsed.query)`` would see nothing.
    """
    value = (fragment or "").strip()
    if "?" in value:
        value = value.split("?", 1)[1]
    return urllib.parse.parse_qs(value)


def parse_lecture_url(url_or_sub_id: str) -> Dict[str, str]:
    """Extract course_id, sub_id, and tenant_code from a replay URL or sub_id.

    Accepts both classroom link shapes:
    - ``https://classroom.zju.edu.cn/livingroom?course_id=...&sub_id=...``
    - ``https://interactivemeta.cmc.zju.edu.cn/#/replay?course_id=...&sub_id=...``
    - a short query string ``?sub_id=456``
    - a pure sub_id integer string ``"456"``
    """
    url_or_sub_id = url_or_sub_id.strip()
    if not url_or_sub_id:
        raise ZJUAPIError("URL 或 sub_id 不能为空")

    # If it's a numeric string, treat directly as sub_id
    if url_or_sub_id.isdigit():
        return {
            "course_id": "",
            "sub_id": url_or_sub_id,
            "tenant_code": "112",
        }

    try:
        parsed = urllib.parse.urlparse(url_or_sub_id)
        query = urllib.parse.parse_qs(parsed.query)
        # Hash routes keep the replay parameters after ``#``. Merge them in
        # only when the outer query has no sub_id, so a normal livingroom URL
        # cannot be overridden by an unrelated fragment.
        if parsed.fragment and not query.get("sub_id"):
            for key, values in _fragment_query(parsed.fragment).items():
                query.setdefault(key, values)
    except Exception as e:
        raise ZJUAPIError(f"URL 格式解析失败: {e}")

    sub_id = query.get("sub_id", [None])[0]
    if not sub_id:
        # Check path segments just in case
        parts = [p for p in parsed.path.split("/") if p]
        for idx, part in enumerate(parts):
            if part in ("sub_id", "record", "livingroom") and idx + 1 < len(parts) and parts[idx + 1].isdigit():
                sub_id = parts[idx + 1]
                break

    if not sub_id:
        raise ZJUAPIError(
            "无法从 URL 中识别 sub_id。请粘贴完整回放地址，支持两种形态：\n"
            "  · https://classroom.zju.edu.cn/livingroom?course_id=...&sub_id=...\n"
            "  · https://interactivemeta.cmc.zju.edu.cn/#/replay?course_id=...&sub_id=..."
        )

    return {
        "course_id": query.get("course_id", [""])[0],
        "sub_id": str(sub_id),
        "tenant_code": query.get("tenant_code", ["112"])[0],
    }


_CLOCK_RE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")


def _clock_seconds(value: Any) -> Optional[int]:
    """Parse ``HH:MM[:SS]`` (or a full datetime) into seconds of day."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    match = _CLOCK_RE.search(text)
    if not match:
        return None
    hour, minute, second = match.group(1), match.group(2), match.group(3) or "0"
    return int(hour) * 3600 + int(minute) * 60 + int(second)


def _transcript_text(item: Dict[str, Any]) -> str:
    for key in ("Text", "zhtext", "TransText", "entext"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def fetch_transcript(
    sub_id: str,
    tenant_code: str = "112",
    timeout: int = 60,
    *,
    cookie: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch transcript segments, optionally authenticating with a local session.

    The primary classroom backend is tried first. When a cookie is supplied,
    the interactive-classroom backend (``interactivemeta.cmc.zju.edu.cn``) is
    tried as a fallback; both accept the same ``search-trans-result`` path and
    the Bearer token extracted from ``_token``. Subtitle requests deliberately
    do **not** send the Cookie header: the Bearer token alone is sufficient and
    keeps the credential surface minimal.
    """
    query = urllib.parse.urlencode({"sub_id": sub_id, "tenant_code": tenant_code, "format": "json"})
    path = f"/courseapi/v3/web-socket/search-trans-result?{query}"

    token: Optional[str] = None
    if cookie is not None:
        cookie = sanitize_cookie_header(cookie)
        REDACTOR.add_cookie(cookie)
        token = extract_classroom_token(cookie)
        if not token:
            raise ZJUAPIError(
                "本地登录态缺少可用的 _token，无法进行字幕鉴权；请重新登录智云课堂并更新本机登录态。"
            )
        REDACTOR.add(token)
        origins = (BASE_URL, INTERACTIVE_BASE_URL)
    else:
        origins = (BASE_URL,)

    data: Optional[Dict[str, Any]] = None
    last_error = ""
    auth_status: Optional[int] = None
    saw_non_auth_error = False
    for origin in origins:
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"{origin}/",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            payload = json.loads(_fetch_bytes(f"{origin}{path}", headers, timeout).decode("utf-8"))
        except urllib.error.HTTPError as error:
            error.close()
            last_error = f"HTTP {error.code}"
            if error.code in (401, 403):
                auth_status = error.code
            else:
                saw_non_auth_error = True
            continue
        except Exception as error:  # noqa: BLE001 - aggregate attempts below
            last_error = REDACTOR.redact(describe_network_error(error))
            saw_non_auth_error = True
            continue

        if not isinstance(payload, dict):
            last_error = "接口返回了非对象 JSON，可能改版了"
            saw_non_auth_error = True
            continue
        code = payload.get("code")
        if code != 0:
            message = REDACTOR.redact(payload.get("msg") or f"未知错误 (code={code})")
            last_error = f"字幕接口返回非零状态码: {message}"
            saw_non_auth_error = True
            continue
        if not payload.get("list"):
            last_error = "字幕数据列表为空，可能课程刚结束尚未生成字幕或该课程未开启录制转写"
            saw_non_auth_error = True
            continue
        data = payload
        break

    if data is None:
        if cookie is None:
            if auth_status is not None:
                raise TranscriptAuthError(auth_status)
            raise ZJUAPIError("请求字幕接口失败。\n" + last_error)
        if auth_status is not None and not saw_non_auth_error:
            raise TranscriptAuthError(auth_status)
        raise ZJUAPIError(
            "字幕接口抓取失败（主站与互动式课堂后端均不可用）。\n"
            + (last_error or "未获得可用的字幕响应")
        )

    raw_segments = data["list"][0].get("all_content") or []
    # 老课程（trans_type="ai"）只有 time/zhtext/entext，没有 BeginSec；
    # 用第一条时间戳作为相对零点，至少保证顺序与间隔正确。
    uses_clock = not any(item.get("BeginSec") not in (None, "") for item in raw_segments)
    clock_base: Optional[int] = None
    if uses_clock:
        clock_base = next(
            (clock for clock in (_clock_seconds(item.get("time")) for item in raw_segments) if clock is not None),
            None,
        )

    segments: List[Dict[str, Any]] = []
    for item in raw_segments:
        text = _transcript_text(item)
        if not text:
            continue
        if uses_clock:
            clock = _clock_seconds(item.get("time"))
            if clock is None or clock_base is None:
                continue
            sec = max(0, clock - clock_base)
        else:
            try:
                sec = int(item.get("BeginSec"))
            except (TypeError, ValueError):
                continue
        segments.append({"begin_sec": sec, "text": text})

    segments.sort(key=lambda x: x["begin_sec"])
    if not segments:
        raise ZJUAPIError("字幕内容经清洗后为空")

    return segments


def _record(diagnostics: Optional[List[str]], message: str) -> None:
    """Collect a degradation reason for the caller to surface (never raises)."""
    if diagnostics is not None:
        diagnostics.append(message)


_CLASSROOM_TOKEN_RE = re.compile(
    r'\{i:\d+;s:\d+:"_token";i:\d+;s:\d+:"([^"]+)";\}'
)


def is_zju_host(host: Optional[str]) -> bool:
    """True for ``zju.edu.cn`` and its subdomains (never lookalikes)."""
    value = (host or "").strip().lower().strip(".")
    return value == "zju.edu.cn" or value.endswith(".zju.edu.cn")


_IMAGE_HOST_SUFFIXES = (
    ".zju.edu.cn",
    ".chinamcloud.com",
    ".chinamcloud.cn",
    ".chinamcache.com",
)


def is_allowed_image_host(host: Optional[str]) -> bool:
    """True for ZJU hosts and the official image CDNs used by the classroom.

    The interactive-classroom projector backend may return screenshots from
    ``chinamcloud`` / ``chinamcache``. These are a closed allowlist, never a
    wildcard: lookalikes such as ``evilchinamcloud.com`` do not match.
    """
    value = (host or "").strip().lower().rstrip(".")
    if not value:
        return False
    if is_zju_host(value):
        return True
    return any(
        value == suffix.lstrip(".") or value.endswith(suffix)
        for suffix in _IMAGE_HOST_SUFFIXES
    )


def secure_zju_url(url: str) -> str:
    """Upgrade ZJU ``http://`` URLs to HTTPS; leave other URLs untouched.

    The classroom SSO cookie has no ``Secure`` flag, so downloading a
    screenshot over plain HTTP would send the login credential unencrypted.
    """
    value = (url or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme.lower() == "http" and is_zju_host(parsed.hostname):
        return "https" + value[4:]
    return value


def secure_image_url(url: str) -> str:
    """Normalise an image URL and upgrade allowed image hosts to HTTPS."""
    value = (url or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme.lower() == "http" and is_allowed_image_host(parsed.hostname):
        return "https" + value[4:]
    return value


def extract_classroom_token(cookie_header: str) -> Optional[str]:
    """Extract the classroom Bearer token from a Cookie header.

    The token is not a cookie of its own: the classroom session cookie stores
    a percent-encoded PHP-serialized payload and ``_token`` is a field inside
    it. Plain ``_token=...`` is accepted as a fallback for hand-written
    cookie files. Returns ``None`` when no usable token is present.
    """
    if not cookie_header:
        return None
    decoded = urllib.parse.unquote(cookie_header)
    match = _CLASSROOM_TOKEN_RE.search(decoded)
    token = match.group(1) if match else ""
    if not token:
        for part in decoded.split(";"):
            name, separator, value = part.partition("=")
            if separator and name.strip() == "_token":
                token = value.strip()
                break
    token = token.strip()
    if not token or len(token) > 4096:
        return None
    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in token):
        return None
    return token


def _classroom_headers(
    cookie: str,
    token: Optional[str],
    sub_id: str,
    origin: str = BASE_URL,
) -> Dict[str, str]:
    """Headers shared by the authenticated classroom endpoints.

    ``origin`` is the API backend actually being queried. The cookie/token are
    still only sent to ZJU hosts; callers must not pass an arbitrary origin.
    """
    if origin not in (BASE_URL, INTERACTIVE_BASE_URL):
        raise ValueError("拒绝向非浙大官方主机发送课堂凭据")
    referer = (
        f"{origin}/livingroom?sub_id={sub_id}"
        if origin == BASE_URL
        else f"{origin}/"
    )
    headers = {
        "User-Agent": USER_AGENT,
        "Cookie": cookie,
        "Referer": referer,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


_SLIDE_CAPTURE_RE = re.compile(r"/(\d{13})\.(?:jpe?g|png)(?:\?.*)?$", re.IGNORECASE)
_CAPTURE_MIN_MS = 946684800000   # 2000-01-01T00:00:00Z
_CAPTURE_MAX_MS = 4102444800000  # 2100-01-01T00:00:00Z


def _slide_capture_ms(image_url: str) -> Optional[int]:
    """Read the capture time encoded in a classroom screenshot URL.

    ``search-ppt`` returns image URLs whose basename is a 13-digit epoch
    millisecond timestamp, e.g. ``.../1794441389000.jpg``.  That timestamp is
    the only page-time signal the API gives us, and it lines up with the
    transcript duration almost exactly (within seconds for a 100-minute
    lecture), so it is worth keeping instead of discarding.
    """
    raw = str(image_url or "").strip()
    if not raw:
        return None
    try:
        path = urllib.parse.urlparse(raw).path
    except ValueError:
        return None
    match = _SLIDE_CAPTURE_RE.search(path)
    if not match:
        return None
    value = int(match.group(1))
    if not _CAPTURE_MIN_MS <= value <= _CAPTURE_MAX_MS:
        return None
    return value


def normalize_slide(item: Any, index: int) -> Dict[str, Any]:
    """Flatten one ``search-ppt`` row into a stable slide record.

    ``content`` is a JSON *string* in the real response
    (``{"pptimgurl": "http://..."}``), not note text. The old formatter
    rendered that string verbatim, so the model saw JSON instead of slides.
    """
    row = item if isinstance(item, dict) else {}
    content_raw = row.get("content")
    parsed: Dict[str, Any] = {}
    text = ""

    if isinstance(content_raw, dict):
        parsed = content_raw
    elif isinstance(content_raw, str):
        stripped = content_raw.strip()
        if stripped.startswith("{"):
            try:
                decoded = json.loads(stripped)
            except ValueError:
                decoded = None
            if isinstance(decoded, dict):
                parsed = decoded
            else:
                text = stripped
        else:
            text = stripped

    def pick(*keys: str) -> str:
        for source in (parsed, row):
            for key in keys:
                value = _clean_text(source.get(key))
                if value:
                    return value
        return ""

    image_url = secure_image_url(
        pick("pptimgurl", "ppt_img_url", "image_url", "imgurl")
    )
    text = text or pick("ocr_content", "ocr_text", "text", "ppttext", "ppt_text")
    slide: Dict[str, Any] = {
        "page": index,
        "image_url": image_url,
        "text": text,
    }
    capture_ms = _slide_capture_ms(image_url)
    if capture_ms is not None:
        slide["capture_ms"] = capture_ms
    time_point = _first_not_none(
        row.get("time"),
        row.get("time_point"),
        row.get("sec"),
        parsed.get("time"),
        parsed.get("time_point"),
    )
    if time_point is not None:
        slide["time"] = time_point
    if not image_url and not text:
        slide["raw"] = json.dumps(item, ensure_ascii=False)[:500]
    return slide


def _apply_slide_time_axis(slides: List[Dict[str, Any]]) -> None:
    """Turn URL capture timestamps into transcript-relative seconds.

    The first captured page is the zero point.  This keeps the slide index
    aligned with the ``[HH:MM]`` transcript timestamps without needing the
    wall-clock lecture start.  API-provided ``time`` values win; they are
    left untouched.
    """
    captures = [
        (slide, slide.get("capture_ms"))
        for slide in slides
        if isinstance(slide.get("capture_ms"), int)
    ]
    if not captures:
        return
    base = min(int(value) for _slide, value in captures)
    for slide, value in captures:
        if slide.get("time") is not None:
            continue
        slide["time"] = max(0, int(round((int(value) - base) / 1000.0)))


def fetch_slides(
    sub_id: str,
    tenant_code: str = "112",
    cookie: Optional[str] = None,
    timeout: int = 30,
    diagnostics: Optional[List[str]] = None,
    course_id: str = "",
) -> Optional[List[Dict[str, Any]]]:
    """Fetch projected-slide screenshots from the classroom API.

    The endpoint returns **screenshots** (``content.pptimgurl``), not a text
    layer. Pagination is required because the API returns at most ~100 rows
    per page; it also sometimes ignores ``per_page`` and repeats the first
    page, so URLs are de-duplicated in order.

    The main classroom backend is queried first; when it returns an empty deck
    or a transport/business failure, the interactive-classroom backend
    (``interactivemeta.cmc.zju.edu.cn/pptnoteapi``) is tried. Auth failures
    (401/403) are not retried against the fallback: the same session is bad and
    the user needs to log in again.

    Requires a login cookie that contains the classroom ``_token`` (found in
    the parent-domain ``.zju.edu.cn`` session cookie). ``diagnostics`` records
    one human-readable degradation reason on failure.
    """
    if not cookie:
        _record(diagnostics, "未提供登录 Cookie")
        return None

    try:
        cookie = sanitize_cookie_header(cookie)
    except ValueError as error:
        _record(diagnostics, f"Cookie 头未通过校验：{error}")
        return None

    token = extract_classroom_token(cookie)
    backends = (
        (BASE_URL, "/pptnote"),
        (INTERACTIVE_BASE_URL, "/pptnoteapi"),
    )
    max_pages = 50
    slides: List[Dict[str, Any]] = []
    total = 0
    last_reason = ""
    reached_limit = False

    for origin, prefix in backends:
        headers = _classroom_headers(cookie, token, sub_id, origin=origin)
        endpoint = f"{origin}{prefix}/v1/schedule/search-ppt"
        backend_slides: List[Dict[str, Any]] = []
        seen: set = set()
        backend_total = 0
        page = 1

        while page <= max_pages:
            params = {
                "sub_id": sub_id,
                "tenant_code": tenant_code,
                "page": page,
                "per_page": 100,
            }
            if course_id:
                params["course_id"] = course_id
            url = f"{endpoint}?{urllib.parse.urlencode(params)}"
            try:
                data = json.loads(_fetch_bytes(url, headers, timeout).decode("utf-8"))
            except urllib.error.HTTPError as error:
                if error.code in (401, 403):
                    hint = "；登录态无效或 Cookie 缺少 _token，请重新登录智云课堂后重试"
                    _record(diagnostics, f"PPT 接口返回 HTTP {error.code}{hint}")
                    return None
                last_reason = "PPT 接口请求失败。" + describe_network_error(error)
                break
            except Exception as error:  # noqa: BLE001 - degradation path, reason is recorded
                last_reason = "PPT 接口请求失败。" + describe_network_error(error)
                break

            if not isinstance(data, dict):
                last_reason = "PPT 接口返回了非对象 JSON，可能改版了"
                break

            code = data.get("code")
            if code != 0:
                message = data.get("msg") or f"未知错误 (code={code})"
                hint = (
                    ""
                    if token
                    else "；Cookie 中未解析到 _token，请确认包含父域 .zju.edu.cn 的会话 Cookie"
                )
                last_reason = f"PPT 接口返回 code={code}: {message}{hint}"
                break

            items = data.get("list") or []
            try:
                page_total = int(data.get("total") or 0)
            except (TypeError, ValueError):
                page_total = 0
            if page_total:
                backend_total = page_total

            added = 0
            for item in items:
                slide = normalize_slide(item, len(backend_slides) + 1)
                key = (
                    slide.get("image_url")
                    or slide.get("text")
                    or json.dumps(item, sort_keys=True, ensure_ascii=False)
                )
                if key in seen:
                    continue
                seen.add(key)
                backend_slides.append(slide)
                added += 1

            # The API may return the whole deck on page 1 and repeat it on page 2.
            if not items or added == 0:
                break
            if backend_total and len(backend_slides) >= backend_total:
                break
            page += 1

        if backend_slides:
            slides = backend_slides
            total = backend_total
            reached_limit = page > max_pages and (not total or len(slides) < total)
            break

    if not slides:
        if last_reason:
            _record(diagnostics, last_reason)
        elif not course_id:
            _record(
                diagnostics,
                "PPT 列表为空；如果输入的是纯 sub_id，请补上 course_id"
                "（完整回放 URL 通常带有 course_id=...）后重试",
            )
        else:
            _record(diagnostics, "PPT 列表为空：老师可能没有使用智云投屏，或截图尚未生成")
        return None

    if total and len(slides) < total:
        _record(
            diagnostics,
            f"PPT 接口标记共 {total} 张，去重后取到 {len(slides)} 张（后续分页无新数据）",
        )
    if reached_limit:
        _record(diagnostics, f"PPT 分页达到上限 {max_pages} 页，已停止")
    _apply_slide_time_axis(slides)
    return slides


def _find_mp4_in_json(obj: Any) -> Optional[str]:
    """Recursively search for first mp4 URL inside nested JSON response."""
    if isinstance(obj, str):
        if obj.startswith("http") and ".mp4" in obj.split("?")[0]:
            return obj
        return None
    if isinstance(obj, dict):
        for v in obj.values():
            found = _find_mp4_in_json(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_mp4_in_json(item)
            if found:
                return found
    return None


def fetch_video_url(
    course_id: str,
    sub_id: str,
    tenant_code: str = "112",
    cookie: Optional[str] = None,
    timeout: int = 30,
    diagnostics: Optional[List[str]] = None,
) -> Optional[str]:
    """Fetch direct MP4 replay video URL from play template config.

    Requires user authentication cookie. Returns ``None`` on any failure, but
    appends the reason to ``diagnostics`` so the caller can tell "没登录" apart
    from "网络坏了".
    """
    if not cookie:
        _record(diagnostics, "未提供登录 Cookie")
        return None

    try:
        cookie = sanitize_cookie_header(cookie)
    except ValueError as error:
        _record(diagnostics, f"Cookie 头未通过校验：{error}")
        return None

    url = (
        f"{BASE_URL}/courseapi/v2/play-template/get-config"
        f"?course_id={course_id}&sub_id={sub_id}&tenant_code={tenant_code}"
    )
    headers = _classroom_headers(
        cookie,
        extract_classroom_token(cookie),
        sub_id,
    )
    try:
        data = json.loads(_fetch_bytes(url, headers, timeout).decode("utf-8"))
        found = _find_mp4_in_json(data)
        if not found:
            _record(diagnostics, "play-template 响应里没有找到 mp4 直链")
        return found
    except Exception as error:  # noqa: BLE001 - degradation path, reason is recorded
        _record(diagnostics, "视频直链接口请求失败。" + describe_network_error(error))
        return None
