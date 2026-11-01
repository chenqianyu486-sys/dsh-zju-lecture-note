# -*- coding: utf-8 -*-
"""
Client for Zhejiang University 智云课堂 (classroom.zju.edu.cn) APIs.
Pure Python standard library implementation with zero external dependencies.
"""

import http.client
import json
import os
import random
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .security import sanitize_cookie_header

BASE_URL = "https://classroom.zju.edu.cn"
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


def _proxy_env() -> str:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(key)
        if value:
            return f"{key}={value}"
    return "(未设置)"


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
) -> bytes:
    """GET ``url`` and read the **whole** body, retrying transient failures.

    The retry has to cover ``read()``, not just the handshake. ``urllib`` builds the
    TLS connection lazily on first use and the body arrives afterwards, so a flaky
    proxy can走完 TCP 握手之后才在读取阶段丢包，表现为
    ``IncompleteRead(201704 bytes read)`` / ``EOF occurred in violation of protocol``。
    只重试建连的话，这类失败仍然一次就穿透到用户面前。

    Certification failures are *not* retried: they need a fix, not a rerun.
    """
    total = max(1, attempts)
    last: Optional[BaseException] = None
    for index in range(total):
        try:
            with _open_request(url, headers, timeout) as response:
                return response.read()
        except Exception as error:  # noqa: BLE001 - re-raised below unless transient
            if not _is_transient(error):
                raise
            last = error
            if index + 1 < total:
                time.sleep(_RETRY_BASE_DELAY * (2**index) + random.uniform(0, 0.25))
    assert last is not None
    raise last


class _SameHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only on the classroom host.

    ``urllib`` re-sends request headers on a redirect, so a compromised or
    misconfigured endpoint that answers ``302`` to another origin would leak
    the ``Cookie`` header. Cross-origin redirects are refused instead.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        target = (urllib.parse.urlparse(newurl).hostname or "").lower()
        if target != BASE_HOST:
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                f"拒绝跨域重定向到 {target or '(未知主机)'}（保护登录 Cookie）",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_request(url: str, headers: Dict[str, str], timeout: int):
    """Open ``url`` with certificate verification and same-host redirects."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=get_ssl_context()),
        _SameHostRedirectHandler(),
    )
    request = urllib.request.Request(url, headers=headers)
    return opener.open(request, timeout=timeout)


class ZJUAPIError(Exception):
    """Raised when an API call to ZJU Classroom fails."""
    pass


def parse_lecture_url(url_or_sub_id: str) -> Dict[str, str]:
    """Extract course_id, sub_id, and tenant_code from a classroom URL or sub_id.
    
    Accepts:
    - Full livingroom URL: https://classroom.zju.edu.cn/livingroom?course_id=123&sub_id=456&tenant_code=112
    - Short query string: ?sub_id=456
    - Pure sub_id integer string: "456"
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
        raise ZJUAPIError("无法从 URL 中识别 sub_id 参数，请确认输入包含有效 sub_id")

    return {
        "course_id": query.get("course_id", [""])[0],
        "sub_id": str(sub_id),
        "tenant_code": query.get("tenant_code", ["112"])[0],
    }


def fetch_transcript(
    sub_id: str,
    tenant_code: str = "112",
    timeout: int = 60
) -> List[Dict[str, Any]]:
    """Fetch speech-to-text transcript segments from public ZJU classroom API.
    
    NOTE: This endpoint is completely PUBLIC and requires no login or cookies.
    Returns:
        List of dicts: [{"begin_sec": int, "text": str}]
    """
    url = (
        f"{BASE_URL}/courseapi/v3/web-socket/search-trans-result"
        f"?sub_id={sub_id}&tenant_code={tenant_code}"
    )
    req_headers = {"User-Agent": USER_AGENT}
    try:
        data = json.loads(_fetch_bytes(url, req_headers, timeout).decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ZJUAPIError(f"字幕接口返回 HTTP {e.code}（已重试 {_RETRY_ATTEMPTS} 次）") from e
    except Exception as e:
        raise ZJUAPIError(
            f"请求字幕接口失败（已重试 {_RETRY_ATTEMPTS} 次）。\n" + describe_network_error(e)
        ) from e

    code = data.get("code")
    if code != 0:
        msg = data.get("msg") or f"未知错误 (code={code})"
        raise ZJUAPIError(f"字幕接口返回非零状态码: {msg}")

    items = data.get("list") or []
    if not items:
        raise ZJUAPIError("字幕数据列表为空，可能课程刚结束尚未生成字幕或该课程未开启录制转写")

    raw_segments = items[0].get("all_content") or []
    segments: List[Dict[str, Any]] = []
    for item in raw_segments:
        text = (item.get("Text") or "").strip()
        if text:
            sec = int(item.get("BeginSec", 0))
            segments.append({"begin_sec": sec, "text": text})

    segments.sort(key=lambda x: x["begin_sec"])
    if not segments:
        raise ZJUAPIError("字幕内容经清洗后为空")

    return segments


def _record(diagnostics: Optional[List[str]], message: str) -> None:
    """Collect a degradation reason for the caller to surface (never raises)."""
    if diagnostics is not None:
        diagnostics.append(message)


def fetch_slides(
    sub_id: str,
    tenant_code: str = "112",
    cookie: Optional[str] = None,
    timeout: int = 30,
    diagnostics: Optional[List[str]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Fetch projected slide notes (PPT text layer) from classroom API.

    Requires a login cookie for authentication. Returns ``None`` when the
    cookie is absent or the request fails, so the caller can degrade to a
    transcript-only lecture note.

    ``diagnostics``（可选）会被追加一条人类可读的降级原因。以前这里 ``except
    Exception: pass``，于是 TLS / 代理故障与"老师没开 PPT"在调用方看来一模一样，
    模型只能猜"是不是没登录"。
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
        f"{BASE_URL}/pptnote/v1/schedule/search-ppt"
        f"?sub_id={sub_id}&tenant_code={tenant_code}"
    )
    headers = {
        "User-Agent": USER_AGENT,
        "Cookie": cookie,
        "Referer": f"{BASE_URL}/livingroom?sub_id={sub_id}",
    }
    try:
        data = json.loads(_fetch_bytes(url, headers, timeout).decode("utf-8"))
        if data.get("code") == 0 and data.get("list"):
            return data["list"]
        _record(diagnostics, f"PPT 接口返回 code={data.get('code')}，无 list 数据")
    except Exception as error:  # noqa: BLE001 - degradation path, reason is recorded
        _record(diagnostics, "PPT 接口请求失败。" + describe_network_error(error))
    return None


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
    headers = {
        "User-Agent": USER_AGENT,
        "Cookie": cookie,
        "Referer": f"{BASE_URL}/livingroom?sub_id={sub_id}",
    }
    try:
        data = json.loads(_fetch_bytes(url, headers, timeout).decode("utf-8"))
        found = _find_mp4_in_json(data)
        if not found:
            _record(diagnostics, "play-template 响应里没有找到 mp4 直链")
        return found
    except Exception as error:  # noqa: BLE001 - degradation path, reason is recorded
        _record(diagnostics, "视频直链接口请求失败。" + describe_network_error(error))
        return None
