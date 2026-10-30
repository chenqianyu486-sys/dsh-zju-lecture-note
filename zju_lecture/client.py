# -*- coding: utf-8 -*-
"""
Client for Zhejiang University 智云课堂 (classroom.zju.edu.cn) APIs.
Pure Python standard library implementation with zero external dependencies.
"""

import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def create_ssl_context() -> ssl.SSLContext:
    """Create a resilient SSL context.

    Attempts standard verification, then certifi if available,
    and falls back to an unverified context if local root certificates are
    missing. The fallback is announced on stderr because it disables
    certificate verification for every request made with it.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass

    ctx = ssl.create_default_context()
    try:
        import socket
        with socket.create_connection(("classroom.zju.edu.cn", 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname="classroom.zju.edu.cn"):
                return ctx
    except Exception:
        pass

    print(
        "[zju-lecture] 本机缺少可用的根证书，SSL 证书校验已关闭（仅回退路径）。",
        file=sys.stderr,
    )
    fallback_ctx = ssl.create_default_context()
    fallback_ctx.check_hostname = False
    fallback_ctx.verify_mode = ssl.CERT_NONE
    return fallback_ctx


_SSL_CONTEXT: Optional[ssl.SSLContext] = None


def get_ssl_context() -> ssl.SSLContext:
    """Return the shared SSL context, building it on first use.

    Building it lazily keeps MCP server startup fast: the probe opens a
    socket to the classroom host.
    """
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = create_ssl_context()
    return _SSL_CONTEXT
BASE_URL = "https://classroom.zju.edu.cn"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


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
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=get_ssl_context()) as response:
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
    Requires user cookie for authentication. Returns None if cookie is absent or request fails.
    """
    if not cookie:
        return None

    url = (
        f"{BASE_URL}/pptnote/v1/schedule/search-ppt"
        f"?sub_id={sub_id}&tenant_code={tenant_code}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Cookie": cookie,
            "Referer": f"{BASE_URL}/livingroom?sub_id={sub_id}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=get_ssl_context()) as response:
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
    Requires user authentication cookie.
    """
    if not cookie:
        return None

    url = (
        f"{BASE_URL}/courseapi/v2/play-template/get-config"
        f"?course_id={course_id}&sub_id={sub_id}&tenant_code={tenant_code}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Cookie": cookie,
            "Referer": f"{BASE_URL}/livingroom?sub_id={sub_id}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=get_ssl_context()) as response:
            data = json.loads(response.read().decode("utf-8"))
        return _find_mp4_in_json(data)
    except Exception:
        return None
