#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZJU Lecture Summarizer - Model Context Protocol (MCP) Server.

Standard stdio JSON-RPC 2.0 server with ZERO external dependencies.
Compatible with DeepSeek Harness (dsh), MiniMax Code, Claude Code, Cursor,
Cline, Windsurf, and OpenAI-style function-calling harnesses.

Design notes:
* stdout carries JSON-RPC only; every diagnostic goes to stderr.
* stdio is forced to UTF-8 so Chinese payloads survive a non-UTF-8 locale.
* Privacy boundary: a login cookie is read from the local browser (or from the
  ``ZJU_COOKIE`` / ``ZJU_COOKIE_FILE`` local configuration) into process memory
  and is *never* a tool argument and *never* a tool result. Every outbound
  string additionally passes through a redactor, so a cookie cannot leak
  through an error message, a traceback or a future debug print.
* Local file tools only accept courseware/notes and refuse credential stores,
  browser databases and key material.
"""

import json
import os
import sys
import traceback
from typing import Any, Dict, List, Optional, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from zju_lecture.client import (
    ZJUAPIError,
    fetch_slides,
    fetch_transcript,
    fetch_video_url,
    parse_lecture_url,
)
from zju_lecture.cookies import CookieAccessError, read_edge_cookies
from zju_lecture.courseware import CoursewareError, extract_courseware_text
from zju_lecture.note_lint import check_markdown, fix_markdown, format_report
from zju_lecture.formatter import (
    build_transcript_views,
    chunk_transcript,
    filter_segments,
    format_slides_as_markdown,
    format_timestamp,
)
from zju_lecture.security import (
    NOTE_EXTENSIONS,
    REDACTOR,
    LocalFileError,
    describe_cookie,
    guard_local_file,
    sanitize_cookie_header,
)

SERVER_NAME = "zju-lecture-mcp"
SERVER_VERSION = "1.3.2"
DEFAULT_TENANT = "112"
DEFAULT_DOMAIN = "classroom.zju.edu.cn"

#: Local, host-controlled cookie sources. Nothing here is model-supplied.
COOKIE_ENV = "ZJU_COOKIE"
COOKIE_FILE_ENV = "ZJU_COOKIE_FILE"
_MAX_COOKIE_FILE_BYTES = 64 * 1024

SERVER_INSTRUCTIONS = (
    "提供浙大智云课堂（classroom.zju.edu.cn）回放的字幕、投影 PPT 与课件文本提取。"
    "字幕接口公开免登录；PPT 与视频直链需要登录态。"
    "登录 Cookie 只在服务端内存中使用，任何工具都不会回显明文，也不接受 cookie 参数。"
    "长课程请使用 view_format=chunked 分批处理。"
)

# Cookies read from the local browser are kept here instead of being handed
# back to the model as plaintext.
_COOKIE_CACHE: Dict[str, str] = {}


def _log(message: str) -> None:
    """Write a diagnostic to stderr with every secret redacted."""
    sys.stderr.write(f"[zju-lecture] {REDACTOR.redact(message)}\n")
    sys.stderr.flush()


def _remember_cookie(cookie: str) -> str:
    """Register a cookie with the process redactor and the in-memory cache."""
    REDACTOR.add_cookie(cookie)
    _COOKIE_CACHE[DEFAULT_DOMAIN] = cookie
    return cookie


def _read_cookie_file(path: str) -> Optional[str]:
    """Read a cookie header from a local file explicitly named by the host."""
    try:
        real_path = os.path.realpath(os.path.expanduser(path))
        if not os.path.isfile(real_path) or os.path.getsize(real_path) > _MAX_COOKIE_FILE_BYTES:
            return None
        with open(real_path, "r", encoding="utf-8") as handle:
            raw = handle.readline().strip()
        return sanitize_cookie_header(raw)
    except (OSError, ValueError):
        return None


def _resolve_cookie() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return ``(cookie, error_message, source)``.

    Source order: in-memory cache → ``ZJU_COOKIE`` → ``ZJU_COOKIE_FILE`` →
    local Edge. The error text is actionable and never contains a cookie
    value.
    """
    cached = _COOKIE_CACHE.get(DEFAULT_DOMAIN)
    if cached:
        return cached, None, "cache"

    raw = os.environ.get(COOKIE_ENV, "").strip()
    if raw:
        try:
            return _remember_cookie(sanitize_cookie_header(raw)), None, "env"
        except ValueError as exc:
            return None, f"{COOKIE_ENV} 中的登录 Cookie 不可用：{exc}", None

    cookie_file = os.environ.get(COOKIE_FILE_ENV, "").strip()
    if cookie_file:
        cookie = _read_cookie_file(cookie_file)
        if cookie:
            return _remember_cookie(cookie), None, "file"
        return None, (
            f"{COOKIE_FILE_ENV} 指向的文件不可用（需要存在、可读、UTF-8、"
            "只含一行 name=value 形式的 Cookie）。"
        ), None

    cookie, error = read_edge_cookies(DEFAULT_DOMAIN)
    if cookie:
        return _remember_cookie(cookie), None, "edge"
    if error is None:
        return None, f"未能从本机 Microsoft Edge 读取到 {DEFAULT_DOMAIN} 的登录 Cookie。", None
    return None, str(error), None


# ---------------------------------------------------------------- Tool schemas

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "zju_parse_url",
        "description": "解析浙大智云课堂 (classroom.zju.edu.cn) 回放链接，提取 sub_id、course_id 与 tenant_code。",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {
                    "type": "string",
                    "description": "智云课堂回放 URL（例如 https://classroom.zju.edu.cn/livingroom?course_id=...&sub_id=...）或纯 sub_id 数字",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "zju_fetch_transcript",
        "description": (
            "抓取智云课堂某节课的语音识别字幕。该接口为浙大公开接口，无需登录或 Cookie 即可获取整节课的语音识别文本。"
            "支持按分钟/秒切片、分块输出以及字符上限截断。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url_or_sub_id": {
                    "type": "string",
                    "description": "回放 URL 或 sub_id",
                },
                "tenant_code": {
                    "type": "string",
                    "description": "租户代码，默认为 112 (浙大)",
                    "default": DEFAULT_TENANT,
                },
                "view_format": {
                    "type": "string",
                    "enum": ["per_minute", "per_segment", "chunked", "json"],
                    "description": (
                        "返回视图格式：'per_minute'（推荐：按分钟整合，带 [时:分] 时间戳）、"
                        "'per_segment'（逐句带秒级时间戳）、"
                        "'chunked'（按约 11k 字符自动分块，便于长课分批总结）、"
                        "'json'（原始数据段）"
                    ),
                    "default": "per_minute",
                },
                "start_minute": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "起始分钟（可选，例如只分析第 30 分钟后的内容）",
                },
                "end_minute": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "结束分钟（可选，例如分析到第 60 分钟为止）",
                },
                "max_chars": {
                    "type": "integer",
                    "minimum": 1000,
                    "description": "单次返回的字符上限（默认 60000）。超出会截断并在末尾标注，长课程建议改用 view_format=chunked",
                    "default": 60000,
                },
            },
            "required": ["url_or_sub_id"],
        },
    },
    {
        "name": "zju_fetch_slides",
        "description": (
            "抓取智云课堂该节课投影现场的 PPT 文字层与 OCR 记录。"
            "需要登录态：服务端会依次尝试内存缓存、ZJU_COOKIE 环境变量、ZJU_COOKIE_FILE 与本机 Edge；"
            "本工具不接受也不回显 Cookie。抓不到时会返回空提示，流水线可降级为纯字幕总结。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url_or_sub_id": {
                    "type": "string",
                    "description": "回放 URL 或 sub_id",
                },
                "tenant_code": {
                    "type": "string",
                    "description": "租户代码，默认为 112",
                    "default": DEFAULT_TENANT,
                },
            },
            "required": ["url_or_sub_id"],
        },
    },
    {
        "name": "zju_extract_courseware",
        "description": (
            "从本地上传的课件（PPTX, DOCX, TXT, MD, CSV, JSON, PDF）中提取纯文本，"
            "用于注入 Agent 上下文以校准专业术语、公式与章节结构。"
            "只接受课件格式；出于隐私保护会拒绝凭据文件、浏览器数据与密钥材料。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "课件文件的绝对路径或相对路径",
                },
                "max_chars": {
                    "type": "integer",
                    "minimum": 100,
                    "description": "最多提取字符数（默认 10000 字符）",
                    "default": 10000,
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "zju_get_video_url",
        "description": (
            "解析回放视频的 MP4 直链（用于本地下载或 Whisper 增强重识别）。需要有效登录态；"
            "服务端自动使用缓存的登录态 / ZJU_COOKIE / 本机 Edge，本工具不接受也不回显 Cookie。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url_or_sub_id": {
                    "type": "string",
                    "description": "回放 URL 或 sub_id",
                },
                "course_id": {
                    "type": "string",
                    "description": "课程 ID（可选，若从完整 URL 解析则自动包含）",
                },
                "tenant_code": {
                    "type": "string",
                    "description": "租户代码，默认为 112",
                    "default": DEFAULT_TENANT,
                },
            },
            "required": ["url_or_sub_id"],
        },
    },
    {
        "name": "zju_check_note",
        "description": (
            "检查已生成的讲义 Markdown 是否符合公式书写规范、能否正常渲染。"
            "静态检查，不联网：捕获表格列被裸竖线截断、行内公式未闭合、"
            "块级公式未独立成行、\\frac 缺花括号、单行 <details> 等会破坏渲染的问题。"
            "传 fix=true 时会先自动修正可机械修复的问题（单行 $$ 块、\\dfrac、\\frac 缺花括号、"
            "表格公式内的裸竖线、单行 <details>）并回写文件，再报告剩余问题。"
            "建议在写完讲义后、交付给用户前调用一次。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "讲义 Markdown 文件的绝对路径或相对路径",
                },
                "fix": {
                    "type": "boolean",
                    "description": "是否自动修正可机械修复的问题并回写文件（默认 false，只检查）",
                    "default": False,
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "zju_read_browser_cookie",
        "description": (
            "从本机 Microsoft Edge 读取已登录的 classroom.zju.edu.cn 登录态，并缓存在 MCP 服务端内存中供其他工具使用。"
            "只返回 Cookie 名称与长度，绝不回显明文；本工具没有任何参数。"
            "注意：Edge 正在运行时会锁住 Cookie 数据库，需要完全退出 Edge 后再调用，"
            "或在宿主配置里设置 ZJU_COOKIE。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
    },
]


# ---------------------------------------------------------------- Tool implementation

def _truncate(text: str, max_chars: Optional[int]) -> str:
    if not max_chars or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[... 内容超过 {max_chars} 字符，已截断；请缩小时间区间或改用 view_format=chunked ...]"


def _dispatch_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Execute the tool function and return the raw response payload."""
    if name == "zju_parse_url":
        parsed = parse_lecture_url(str(arguments.get("url", "")))
        return json.dumps(parsed, ensure_ascii=False, indent=2)

    if name == "zju_fetch_transcript":
        parsed = parse_lecture_url(str(arguments.get("url_or_sub_id", "")))
        sub_id = parsed["sub_id"]
        tenant = arguments.get("tenant_code") or parsed.get("tenant_code") or DEFAULT_TENANT
        view_format = arguments.get("view_format", "per_minute")
        max_chars = arguments.get("max_chars") or 60000

        start_min = arguments.get("start_minute")
        end_min = arguments.get("end_minute")
        start_sec = start_min * 60 if start_min is not None else None
        end_sec = (end_min * 60 + 59) if end_min is not None else None

        raw_segments = fetch_transcript(sub_id, tenant)
        if start_sec is not None or end_sec is not None:
            raw_segments = filter_segments(raw_segments, start_sec, end_sec)

        if not raw_segments:
            return f"未能获取到指定时间区间内的字幕（sub_id={sub_id}）。请确认课程已生成转写，或调整时间区间。"

        per_seg, per_min, minutes_map = build_transcript_views(raw_segments)
        duration_str = format_timestamp(raw_segments[-1]["begin_sec"])

        header = (
            f"=== 浙大智云课堂语音字幕 (sub_id={sub_id}) ===\n"
            f"总句数: {len(raw_segments)} | 课程时间点: ~{duration_str}\n"
        )

        if view_format == "per_segment":
            return _truncate(header + "\n" + per_seg, max_chars)
        if view_format == "chunked":
            chunks = chunk_transcript(minutes_map)
            return json.dumps(
                {"sub_id": sub_id, "total_chunks": len(chunks), "chunks": chunks},
                ensure_ascii=False,
                indent=2,
            )
        if view_format == "json":
            return json.dumps(
                {"sub_id": sub_id, "duration": duration_str, "segments": raw_segments},
                ensure_ascii=False,
                indent=2,
            )
        return _truncate(header + "\n" + per_min, max_chars)

    if name == "zju_fetch_slides":
        parsed = parse_lecture_url(str(arguments.get("url_or_sub_id", "")))
        sub_id = parsed["sub_id"]
        tenant = arguments.get("tenant_code") or parsed.get("tenant_code") or DEFAULT_TENANT

        cookie, cookie_error, _source = _resolve_cookie()
        if not cookie:
            return (
                "未抓取到 PPT 记录。可能原因：\n"
                f"{cookie_error or '未提供登录 Cookie'}\n"
                "2. 老师授课时未通过智云课堂课件系统同步投影\n"
                "（流水线可平滑降级，仅依赖语音字幕完成讲义生成）"
            )

        slides_data = fetch_slides(sub_id, tenant, cookie)
        if not slides_data:
            return (
                "未抓取到 PPT 记录。可能原因：\n"
                "1. 登录 Cookie 无效或已过期\n"
                "2. 老师授课时未通过智云课堂课件系统同步投影\n"
                "（流水线可平滑降级，仅依赖语音字幕完成讲义生成）"
            )

        md = format_slides_as_markdown(slides_data)
        return f"=== 课堂投影 PPT 数据 (共 {len(slides_data)} 页) ===\n\n{md}"

    if name == "zju_extract_courseware":
        file_path = str(arguments.get("file_path", ""))
        max_chars = arguments.get("max_chars") or 10000
        try:
            text = extract_courseware_text(file_path, max_chars)
        except CoursewareError as exc:
            return f"错误: {exc}"
        return (
            f"=== 课件文件提取成功 ({os.path.basename(file_path)}) ===\n"
            f"提取字数: {len(text)} 字符\n\n"
            f"{text}"
        )

    if name == "zju_get_video_url":
        parsed = parse_lecture_url(str(arguments.get("url_or_sub_id", "")))
        sub_id = parsed["sub_id"]
        course_id = arguments.get("course_id") or parsed.get("course_id", "")
        tenant = arguments.get("tenant_code") or parsed.get("tenant_code") or DEFAULT_TENANT

        cookie, cookie_error, _source = _resolve_cookie()
        if not cookie:
            return (
                "错误: 获取视频 MP4 直链需要登录 Cookie。\n"
                f"{cookie_error or '请退出 Edge 后重试，或在宿主配置里设置 ZJU_COOKIE。'}"
            )

        mp4_url = fetch_video_url(course_id, sub_id, tenant, cookie)
        if not mp4_url:
            return f"未能获取到 MP4 视频直链 (sub_id={sub_id}, course_id={course_id})"

        return json.dumps(
            {"sub_id": sub_id, "course_id": course_id, "video_url": mp4_url},
            ensure_ascii=False,
            indent=2,
        )

    if name == "zju_check_note":
        file_path = str(arguments.get("file_path", "")).strip()
        if not file_path:
            raise ValueError("zju_check_note 需要 file_path 参数")
        if not os.path.isfile(os.path.expanduser(file_path)):
            return f"错误: 找不到讲义文件: {file_path}"
        try:
            file_path = guard_local_file(file_path, NOTE_EXTENSIONS, kind="讲义文件")
        except LocalFileError as exc:
            return f"错误: {exc}"
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                note_text = handle.read()
        except UnicodeDecodeError:
            return f"错误: 讲义文件不是 UTF-8 编码: {file_path}"
        except OSError as exc:
            return f"错误: 读取讲义文件失败: {exc}"

        applied = []
        if arguments.get("fix"):
            fixed_text, applied = fix_markdown(note_text)
            if fixed_text != note_text:
                try:
                    with open(file_path, "w", encoding="utf-8", newline="\n") as handle:
                        handle.write(fixed_text)
                except OSError as exc:
                    return f"错误: 回写讲义文件失败: {exc}"
                note_text = fixed_text

        report = format_report(os.path.basename(file_path), check_markdown(note_text))
        if applied:
            applied_block = "\n".join(f"- {item}" for item in applied)
            report = f"=== 已自动修复 ===\n{applied_block}\n\n{report}"
        return report

    if name == "zju_read_browser_cookie":
        cookie, error, source = _resolve_cookie()
        if not cookie:
            return f"未能读取到 {DEFAULT_DOMAIN} 的登录 Cookie。\n{error or ''}"

        info = describe_cookie(cookie)
        return json.dumps(
            {
                "status": "success",
                "domain": DEFAULT_DOMAIN,
                "source": source,
                **info,
                "note": (
                    "登录态已缓存在 MCP 服务端内存中，明文未回显；"
                    "后续 zju_fetch_slides / zju_get_video_url 会自动使用。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    raise ValueError(f"Unknown tool: {name}")


def handle_tool_call(name: str, arguments: Dict[str, Any]) -> Any:
    """Execute a tool and redact secrets from whatever it returns."""
    return REDACTOR.redact(_dispatch_tool(name, arguments))


# ---------------------------------------------------------------- JSON-RPC layer

def send_response(req_id: Any, result: Any) -> None:
    payload = REDACTOR.redact(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}, ensure_ascii=False))
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


def send_error(req_id: Any, code: int, message: str, data: Any = None) -> None:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    payload = REDACTOR.redact(json.dumps({"jsonrpc": "2.0", "id": req_id, "error": error}, ensure_ascii=False))
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


def _tool_result(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": REDACTOR.redact(text)}], "isError": False}


def _tool_error(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": REDACTOR.redact(message)}], "isError": True}


def handle_request(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Handle one JSON-RPC request. Returns None for notifications."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}

    has_id = "id" in message and message["id"] is not None
    req_id = message.get("id")
    method = message["method"]
    params = message.get("params") or {}

    if not has_id:
        # Notification: acknowledged silently, never answered.
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": SERVER_INSTRUCTIONS,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}
        try:
            payload = handle_tool_call(tool_name, tool_args)
        except (ZJUAPIError, CoursewareError, CookieAccessError) as exc:
            message_text = REDACTOR.redact(str(exc))
            _log(f"{tool_name}: {message_text}")
            return {"jsonrpc": "2.0", "id": req_id, "result": _tool_error(message_text)}
        except Exception as exc:  # noqa: BLE001 - the model must see a usable message
            _log(f"{tool_name} failed:\n{traceback.format_exc()}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": _tool_error(f"工具 {tool_name} 执行失败：{exc}（详细信息见服务端 stderr）"),
            }
        return {"jsonrpc": "2.0", "id": req_id, "result": _tool_result(str(payload))}

    if method in ("resources/list", "resources/templates/list"):
        return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}

    if method in ("prompts/list",):
        return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def _configure_stdio() -> None:
    """Force UTF-8 on stdio so Chinese payloads survive any host locale."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> None:
    """Main stdio loop for the Model Context Protocol."""
    _configure_stdio()

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print(f"[{SERVER_NAME} v{SERVER_VERSION}] Self-test mode:")
        print("URL parsing test:", parse_lecture_url(
            "https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456&tenant_code=112"
        ))
        print("Tools loaded:", [t["name"] for t in TOOLS])
        print("Ready for MCP stdio connection.")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--list-tools":
        print(json.dumps(TOOLS, ensure_ascii=False, indent=2))
        return

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except Exception as exc:
            send_error(None, -32700, f"Parse error: {exc}")
            continue
        try:
            response = handle_request(message)
        except Exception as exc:  # noqa: BLE001
            _log(f"handler crashed:\n{traceback.format_exc()}")
            response = {
                "jsonrpc": "2.0",
                "id": message.get("id") if isinstance(message, dict) else None,
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            }
        if response is not None:
            payload = REDACTOR.redact(json.dumps(response, ensure_ascii=False))
            sys.stdout.write(payload + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
