# -*- coding: utf-8 -*-
"""
Client for Zhejiang University 智云课堂 (classroom.zju.edu.cn) APIs.
Pure Python standard library implementation with zero external dependencies.
"""

import json
import ssl
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


def create_ssl_context() -> ssl.SSLContext:
    """Create the TLS context used for every request.

    Certificate verification is **never** disabled. The login cookie is sent
    over this connection, so silently downgrading to an unverified context
    (as an earlier version did when the local root store was incomplete) would
    turn a missing CA bundle into a cookie-exfiltration path. ``certifi`` is
    used when installed; otherwise the system store is the only option, and a
    handshake failure surfaces as an actionable error.
    """
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    return ssl.create_default_context()


_SSL_CONTEXT: Optional[ssl.SSLContext] = None


def get_ssl_context() -> ssl.SSLContext:
    """Return the shared SSL context, building it on first use."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = create_ssl_context()
    return _SSL_CONTEXT


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
        with _open_request(url, req_headers, timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ZJUAPIError(f"字幕接口返回 HTTP 错误: {e.code}")
    except Exception as e:
        raise ZJUAPIError(f"请求字幕接口失败: {e}")

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


def fetch_slides(
    sub_id: str,
    tenant_code: str = "112",
    cookie: Optional[str] = None,
    timeout: int = 30
) -> Optional[List[Dict[str, Any]]]:
    """Fetch projected slide notes (PPT text layer) from classroom API.

    Requires a login cookie for authentication. Returns ``None`` when the
    cookie is absent or the request fails, so the caller can degrade to a
    transcript-only lecture note.
    """
    if not cookie:
        return None

    try:
        cookie = sanitize_cookie_header(cookie)
    except ValueError:
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
        with _open_request(url, headers, timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        if data.get("code") == 0 and data.get("list"):
            return data["list"]
    except Exception:
        pass
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
    timeout: int = 30
) -> Optional[str]:
    """Fetch direct MP4 replay video URL from play template config.

    Requires user authentication cookie. Returns ``None`` on any failure.
    """
    if not cookie:
        return None

    try:
        cookie = sanitize_cookie_header(cookie)
    except ValueError:
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
        with _open_request(url, headers, timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return _find_mp4_in_json(data)
    except Exception:
        return None
