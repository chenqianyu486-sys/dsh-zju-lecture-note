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
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from zju_lecture.client import (
    ZJUAPIError,
    extract_classroom_token,
    fetch_slides,
    fetch_transcript,
    fetch_video_url,
    parse_lecture_url,
)
from zju_lecture.cookies import CookieAccessError, read_edge_cookies
from zju_lecture.courseware import CoursewareError, extract_courseware_text
from zju_lecture.note_lint import (
    check_markdown,
    fix_markdown,
    format_report,
    write_atomic,
    write_with_backup,
)
from zju_lecture.paths import (
    artifact_dir,
    describe_attempts,
    note_target,
    resolve_path,
)
from zju_lecture.slides import build_slides_pdf, download_slides
from zju_lecture.formatter import (
    build_transcript_views,
    chunk_transcript,
    filter_segments,
    format_quality_line,
    format_slides_as_markdown,
    format_timestamp,
    transcript_quality,
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
SERVER_VERSION = "1.5.0"
DEFAULT_TENANT = "112"
DEFAULT_DOMAIN = "classroom.zju.edu.cn"

#: Upper bound for one note passed to ``zju_write_note`` (bytes are larger for
#: Chinese, but a lecture note never legitimately exceeds this).
MAX_NOTE_CHARS = 2 * 1024 * 1024

#: Local, host-controlled cookie sources. Nothing here is model-supplied.
COOKIE_ENV = "ZJU_COOKIE"
COOKIE_FILE_ENV = "ZJU_COOKIE_FILE"
_MAX_COOKIE_FILE_BYTES = 64 * 1024

#: Opt-in: download projected-slide screenshots and reference them in the
#: note. Off by default because it adds download time and vision tokens.
EMBED_SLIDES_ENV = "ZJU_EMBED_SLIDES"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def embed_slides_enabled() -> bool:
    """Whether the host asked for projected-slide images in the note."""
    return str(os.environ.get(EMBED_SLIDES_ENV, "")).strip().lower() in _TRUE_VALUES


SLIDE_IMAGE_MODE_TEXT = (
    "讲义插图模式：开启。需要投影画面时调用 zju_fetch_slides(download=true)，"
    "从返回的截图里挑 3–8 张关键页，按讲义所在目录的相对路径插入 Markdown；"
    "模型不能查看本地图片时，只在文末列截图索引，不要臆造截图内容。"
    if embed_slides_enabled()
    else "讲义插图模式：关闭（默认，节省下载时间与 token）。"
    "用户明确要求插图时再调用 zju_fetch_slides(download=true)。"
)

SERVER_INSTRUCTIONS = (
    "提供浙大智云课堂（classroom.zju.edu.cn）回放的字幕、投影 PPT 截图与课件文本提取。"
    "字幕接口公开免登录；投影截图（可下载并合成 PDF）与视频直链需要登录态（Cookie 需含 _token）。"
    "登录 Cookie 只在服务端内存中使用，任何工具都不会回显明文，也不接受 cookie 参数。"
    "长课程请使用 view_format=chunked 分批处理。"
    "讲义写入用 zju_write_note（统一命名、拒绝静默覆盖、写后自动检查），"
    "相对路径按当前工作区（ZJU_WORKSPACE）解析。"
    + SLIDE_IMAGE_MODE_TEXT
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
    # The Bearer token is a field inside the session cookie value, so the
    # full-value registration above would not mask it on its own.
    token = extract_classroom_token(cookie)
    if token:
        REDACTOR.add(token)
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


def _resolve_cookie() -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return ``(cookie, error_message, source, reason)``.

    Source order: in-memory cache → ``ZJU_COOKIE`` → ``ZJU_COOKIE_FILE`` →
    local Edge. The error text is actionable and never contains a cookie
    value. ``reason`` is a machine-readable code (``abe`` / ``locked`` /
    ``no_rows`` / ``env_invalid`` …) so a caller can print exactly one
    conclusion instead of a list of maybes.
    """
    cached = _COOKIE_CACHE.get(DEFAULT_DOMAIN)
    if cached:
        return cached, None, "cache", None

    raw = os.environ.get(COOKIE_ENV, "").strip()
    if raw:
        try:
            return _remember_cookie(sanitize_cookie_header(raw)), None, "env", None
        except ValueError as exc:
            return None, f"{COOKIE_ENV} 中的登录 Cookie 不可用：{exc}", None, "env_invalid"

    cookie_file = os.environ.get(COOKIE_FILE_ENV, "").strip()
    if cookie_file:
        cookie = _read_cookie_file(cookie_file)
        if cookie:
            return _remember_cookie(cookie), None, "file", None
        return None, (
            f"{COOKIE_FILE_ENV} 指向的文件不可用（需要存在、可读、UTF-8、"
            "只含一行 name=value 形式的 Cookie）。"
        ), None, "file_unreadable"

    cookie, error = read_edge_cookies(DEFAULT_DOMAIN)
    if cookie:
        return _remember_cookie(cookie), None, "edge", None
    if error is None:
        return None, f"未能从本机 Microsoft Edge 读取到 {DEFAULT_DOMAIN} 的登录 Cookie。", None, "no_credentials"
    return None, str(error), None, error.reason


#: One concrete next step per cookie-failure reason.
#:
#: The old code pasted every possibility into one paragraph, which produced
#: messages like "请完全退出 Edge 后重试；本机已启用 ABE，退出 Edge 也无法解密"
#: — advice that contradicts itself and tells the agent nothing about which
#: path to take. Each reason now maps to exactly one action.
COOKIE_FAILURE_ACTIONS: Dict[str, str] = {
    "abe": "退出 Edge 无效（ABE 的密钥与浏览器进程绑定）：请在宿主配置里设置 ZJU_COOKIE_FILE"
    " 环境变量（文件内只放一行 Cookie 头，不要粘贴到对话里），然后重试。",
    "locked": "完全退出 Edge（含后台驻留进程）后重试；或在宿主配置里设置 ZJU_COOKIE_FILE。",
    "no_rows": "先在 Edge 里登录智云课堂，或在宿主配置里设置 ZJU_COOKIE_FILE，然后重试。",
    "decrypt_failed": "Edge 的新版 Cookie 无法在浏览器外解密：改用 ZJU_COOKIE_FILE 环境变量。",
    "not_found": "确认本机 Edge 至少登录过一次智云课堂，或改用 ZJU_COOKIE_FILE。",
    "db_error": "完全退出 Edge 后重试，或改用 ZJU_COOKIE_FILE。",
    "unsupported_platform": "在宿主配置里设置 ZJU_COOKIE_FILE 环境变量。",
    "keychain_denied": "在弹出的钥匙串授权框选择『始终允许』，或改用 ZJU_COOKIE_FILE。",
    "no_credentials": "在宿主配置里设置 ZJU_COOKIE_FILE 环境变量（不要粘贴到对话里）。",
    "env_invalid": "检查 ZJU_COOKIE：需要一行合法的 name=value Cookie 头。",
    "file_unreadable": "检查 ZJU_COOKIE_FILE：需要存在、可读、UTF-8，且只含一行 Cookie 头。",
    "unknown": "在宿主配置里设置 ZJU_COOKIE_FILE 环境变量后重试。",
}


def _cookie_failure_text(
    subject: str,
    reason: Optional[str],
    detail: Optional[str],
    degrade_hint: str = "",
    verb: str = "抓取到",
) -> str:
    """Render exactly one conclusion plus exactly one action."""
    code = reason or "unknown"
    action = COOKIE_FAILURE_ACTIONS.get(code) or COOKIE_FAILURE_ACTIONS["unknown"]
    lines = [
        f"未{verb} {subject}（原因: {code}）。",
        f"说明: {detail or '未提供可用的登录 Cookie。'}",
        f"唯一可行动作: {action}",
    ]
    if degrade_hint:
        lines.append(degrade_hint)
    return "\n".join(lines)


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
            "抓取智云课堂该节课的投影 PPT 截图清单。search-ppt 接口返回的是"
            "投影画面截图（pptimgurl），不是文字层或 OCR；需要阅读幻灯片内容时"
            "请设置 download=true 下载截图并合成 PDF（可用支持视觉的模型查看）。"
            "是否把截图引用进讲义由插件设置 embedSlideImages / 环境变量 ZJU_EMBED_SLIDES 控制"
            "（默认关闭，节省下载时间与 token）。"
            "接口需要登录态且 Cookie 中必须包含 _token：服务端会依次尝试内存缓存、"
            "ZJU_COOKIE 环境变量、ZJU_COOKIE_FILE 与本机 Edge；本工具不接受也不回显 Cookie。"
            "抓不到时返回具体诊断，流水线可降级为纯字幕总结。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url_or_sub_id": {
                    "type": "string",
                    "description": "回放 URL（通常含 course_id）或 sub_id",
                },
                "course_id": {
                    "type": "string",
                    "description": (
                        "课程 ID；从完整回放 URL 自动解析。只输入纯 sub_id 时必须显式提供，"
                        "否则接口可能返回空列表"
                    ),
                },
                "tenant_code": {
                    "type": "string",
                    "description": "租户代码，默认为 112",
                    "default": DEFAULT_TENANT,
                },
                "download": {
                    "type": "boolean",
                    "description": (
                        "是否下载截图到工作区并合成 PDF。省略时跟随插件设置"
                        "（dsh 的 embedSlideImages / 环境变量 ZJU_EMBED_SLIDES，默认关闭）；"
                        "显式传 true/false 可覆盖。一节 1 小时的课通常有几十到几百张截图"
                    ),
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "截图与 PDF 的输出目录，相对当前工作区（默认 ppt-assets/<sub_id>）；"
                        "必须在工作区内"
                    ),
                },
                "dedup": {
                    "type": "boolean",
                    "description": (
                        "是否折叠连续字节完全相同的截图（默认 true，只影响 PDF 页数，"
                        "下载的原图都会保留）"
                    ),
                    "default": True,
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
            "报告按问题类型聚合（同类问题只打印一次，附行号与示例），长讲义也不会刷屏。"
            "传 fix=true 时会先自动修正可机械修复的问题（单行 $$ 块、块级公式前后缺空行、"
            "\\dfrac、\\frac 缺花括号、表格公式内的裸竖线、单行 <details>）并回写文件，再报告剩余问题。"
            "回写前会先把原文件备份到备份目录（ZJU_BACKUP_DIR，默认系统临时目录），报告里给出备份绝对路径。"
            "相对路径按当前工作区解析。建议在写完讲义后、交付给用户前调用一次。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "讲义 Markdown 文件的绝对路径，或相对当前工作区的路径",
                },
                "fix": {
                    "type": "boolean",
                    "description": "是否自动修正可机械修复的问题并回写文件（默认 false，只检查）",
                    "default": False,
                },
                "max_samples": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "每类问题最多列出几个行号示例（默认 3，0 表示只报数量）",
                    "default": 3,
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "zju_write_note",
        "description": (
            "写入讲义 Markdown。文件名由你依据「上课时间 + 本节课内容」起名（如 "
            "知识总结-2026-10-28-复变函数-保角映射），不同讲次不会互相覆盖；"
            "不传 name 时才回退到 知识总结-<sub_id>[-<课程简称>].md。"
            "默认拒绝覆盖同名文件（返回 exists，让人决定改名还是覆盖），覆盖前自动备份。"
            "写入前自动修正可机械修复的公式问题，写入后立即返回渲染规范检查报告——"
            "也就是把「写文件」和「zju_check_note」两步合成一次调用。"
            "只写工作区（当前工作区或 ZJU_WORKSPACE）内的 .md 文件。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sub_id": {
                    "type": "string",
                    "description": "课程回放的 sub_id，用于追溯（不传 name 时也参与文件名）",
                },
                "content": {
                    "type": "string",
                    "description": "讲义 Markdown 全文",
                },
                "name": {
                    "type": "string",
                    "description": (
                        "讲义文件名（可省略 .md），由你按上课时间与本节内容命名，"
                        "推荐 知识总结-<上课日期 YYYY-MM-DD>-<课程简称>-<本节主题>；"
                        "拿不到上课日期时省略日期段，不要用当天日期顶替"
                    ),
                },
                "slug": {
                    "type": "string",
                    "description": "课程简称（可选，仅在不传 name 时用于文件名）",
                },
                "directory": {
                    "type": "string",
                    "description": "工作区内的子目录（可选，例如 notes；不允许跳出工作区）",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "同名文件已存在时是否覆盖（默认 false，返回 exists 让人决定）",
                    "default": False,
                },
                "fix": {
                    "type": "boolean",
                    "description": "写入前是否自动修正可机械修复的问题（默认 true）",
                    "default": True,
                },
                "max_samples": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "检查报告中每类问题最多列出几个行号示例（默认 3）",
                    "default": 3,
                },
            },
            "required": ["sub_id", "content"],
        },
    },
    {
        "name": "zju_read_browser_cookie",
        "description": (
            "从本机 Microsoft Edge 读取已登录的 classroom.zju.edu.cn 登录态（含父域 .zju.edu.cn 的域级 Cookie，"
            "智云的 _token 在那里），并缓存在 MCP 服务端内存中供其他工具使用。"
            "只返回 Cookie 名称与长度，绝不回显明文；本工具没有任何参数。"
            "注意：Edge 正在运行时会锁住 Cookie 数据库；若本机 Edge 启用了应用绑定加密（ABE），"
            "退出 Edge 也无法在本地解密，应改用 ZJU_COOKIE_FILE 环境变量（不要粘贴到对话里）。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
    },
]


# ---------------------------------------------------------------- Tool implementation

def _clamped_max_samples(value: Any, default: int = 3) -> int:
    """Bound how many example lines a lint report prints per problem class."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(number, 50))


def _truncate(text: str, max_chars: Optional[int]) -> str:
    if not max_chars or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[... 内容超过 {max_chars} 字符，已截断；请缩小时间区间或改用 view_format=chunked ...]"


def _hard_truncate(text: str, max_chars: Optional[int]) -> str:
    """Cut ``text`` to the hard budget, without appending a suffix."""
    if not max_chars or len(text) <= max_chars:
        return text
    return text[:max_chars]


def _payload_len(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False, indent=2))


def _fit_prefix(items: List[Any], build, max_chars: int) -> int:
    """Largest prefix length whose JSON payload still fits in ``max_chars``."""
    low, high = 0, len(items)
    while low < high:
        mid = (low + high + 1) // 2
        if _payload_len(build(items[:mid])) <= max_chars:
            low = mid
        else:
            high = mid - 1
    return low


def _chunked_payload(
    sub_id: str,
    minutes_map: Dict[int, List[str]],
    max_chars: int,
    quality: Optional[Dict[str, Any]] = None,
) -> str:
    """Serialize transcript chunks within ``max_chars``.

    ``chunked`` exists for long lectures, so returning every chunk regardless
    of the budget would defeat its purpose. Chunks are built against half the
    budget, then the largest fitting prefix is returned together with
    ``truncated`` / ``next_start_minute`` so the agent can fetch the rest.
    """
    budget = max(1200, max_chars // 2)
    chunks = chunk_transcript(minutes_map, max_chars=budget)

    def build(subset: List[Dict[str, Any]]) -> Dict[str, Any]:
        returned = len(subset)
        payload = {
            "sub_id": sub_id,
            "total_chunks": len(chunks),
            "returned_chunks": returned,
            "truncated": returned < len(chunks),
            "next_start_minute": chunks[returned]["start_min"] if returned < len(chunks) else None,
            "chunks": subset,
        }
        if quality:
            # One small object, so the agent knows how far to trust the text
            # before it starts distilling.
            payload["quality"] = quality
        return payload

    keep = _fit_prefix(chunks, build, max_chars)
    if keep == 0 and chunks:
        first = dict(chunks[0])
        text = str(first.get("text", ""))
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            first["text"] = text[:mid]
            first["char_count"] = mid
            if _payload_len(build([first])) <= max_chars:
                low = mid
            else:
                high = mid - 1
        first["text"] = text[:low]
        first["char_count"] = low
        first["text_truncated"] = True
        payload = json.dumps(build([first]), ensure_ascii=False, indent=2)
        if len(payload) <= max_chars:
            return payload
        return _hard_truncate(json.dumps(build([]), ensure_ascii=False, indent=2), max_chars)
    return json.dumps(build(chunks[:keep]), ensure_ascii=False, indent=2)


def _segments_payload(
    sub_id: str,
    segments: List[Dict[str, Any]],
    duration: str,
    max_chars: int,
    quality: Optional[Dict[str, Any]] = None,
) -> str:
    """Serialize raw segments within ``max_chars``, reporting the cut point."""

    def build(subset: List[Dict[str, Any]]) -> Dict[str, Any]:
        returned = len(subset)
        payload = {
            "sub_id": sub_id,
            "duration": duration,
            "total_segments": len(segments),
            "returned_segments": returned,
            "truncated": returned < len(segments),
            "next_start_minute": (
                segments[returned]["begin_sec"] // 60 if returned < len(segments) else None
            ),
            "segments": subset,
        }
        if quality:
            payload["quality"] = quality
        return payload

    keep = _fit_prefix(segments, build, max_chars)
    payload = json.dumps(build(segments[:keep]), ensure_ascii=False, indent=2)
    return payload if len(payload) <= max_chars else _hard_truncate(payload, max_chars)


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
        full_duration = (
            format_timestamp(raw_segments[-1]["begin_sec"]) if raw_segments else "00:00:00"
        )
        slice_note = ""
        if start_sec is not None or end_sec is not None:
            sliced = filter_segments(raw_segments, start_sec, end_sec)
            if sliced:
                slice_note = (
                    f" | 本次区间: {format_timestamp(sliced[0]['begin_sec'])}"
                    f"-{format_timestamp(sliced[-1]['begin_sec'])} | 本次句数: {len(sliced)}"
                )
            raw_segments = sliced

        if not raw_segments:
            return f"未能获取到指定时间区间内的字幕（sub_id={sub_id}）。请确认课程已生成转写，或调整时间区间。"

        per_seg, per_min, minutes_map = build_transcript_views(raw_segments)
        quality = transcript_quality(raw_segments)
        duration_str = full_duration

        header = (
            f"=== 浙大智云课堂语音字幕 (sub_id={sub_id}) ===\n"
            f"总句数: {len(raw_segments)} | 课程总时长: ~{duration_str}{slice_note}\n"
            f"{format_quality_line(quality)}\n"
        )

        if view_format == "per_segment":
            return _truncate(header + "\n" + per_seg, max_chars)
        if view_format == "chunked":
            return _chunked_payload(sub_id, minutes_map, max_chars, quality)
        if view_format == "json":
            return _segments_payload(sub_id, raw_segments, duration_str, max_chars, quality)
        return _truncate(header + "\n" + per_min, max_chars)

    if name == "zju_fetch_slides":
        parsed = parse_lecture_url(str(arguments.get("url_or_sub_id", "")))
        sub_id = parsed["sub_id"]
        tenant = arguments.get("tenant_code") or parsed.get("tenant_code") or DEFAULT_TENANT
        course_id = str(arguments.get("course_id") or parsed.get("course_id") or "")
        download_arg = arguments.get("download")
        slide_images_enabled = embed_slides_enabled()
        download = slide_images_enabled if download_arg is None else bool(download_arg)
        dedup_arg = arguments.get("dedup")
        dedup = True if dedup_arg is None else bool(dedup_arg)
        output_dir = str(arguments.get("output_dir") or "").strip()

        cookie, cookie_error, _source, reason = _resolve_cookie()
        if not cookie:
            return _cookie_failure_text(
                "PPT 记录",
                reason,
                cookie_error,
                degrade_hint="（流水线可平滑降级：没有 PPT 也能仅凭语音字幕生成讲义。）",
            )

        diagnostics: List[str] = []
        slides_data = fetch_slides(
            sub_id,
            tenant,
            cookie,
            diagnostics=diagnostics,
            course_id=course_id,
        )
        if not slides_data:
            reason_text = "\n".join(f"- {item}" for item in diagnostics) or "- 未获得具体原因"
            return (
                "未抓取到 PPT 记录（原因: no_slides）。\n"
                "登录态可用，但接口没有返回截图列表。\n"
                f"诊断:\n{reason_text}\n"
                "可行动作: 跳过 PPT，仅用语音字幕生成讲义；"
                "或确认回放链接带有 course_id 后重试。"
            )

        pdf_path = ""
        download_note = ""
        note_example = ""
        if download:
            target, target_error = artifact_dir(
                output_dir,
                default=os.path.join("ppt-assets", sub_id),
            )
            if target_error:
                diagnostics.append(target_error)
            else:
                summary = download_slides(
                    slides_data,
                    target,
                    cookie=cookie,
                    sub_id=sub_id,
                    dedup=dedup,
                    diagnostics=diagnostics,
                )
                note_example = str(summary.get("note_example") or "")
                pages = summary.get("pages") or []
                if pages:
                    pdf_target = os.path.join(target, f"PPT-{sub_id}.pdf")
                    written = build_slides_pdf(pages, pdf_target, diagnostics=diagnostics)
                    if written:
                        pdf_path = written
                download_note = (
                    f"下载 {summary.get('downloaded', 0)} 张，失败 {summary.get('failed', 0)} 张，"
                    f"连续重复折叠 {summary.get('duplicates', 0)} 张；"
                    f"截图目录: {summary.get('images_dir')}"
                )
                if pdf_path:
                    download_note += f"\nPDF: {pdf_path}（{len(pages)} 页）"

        md = format_slides_as_markdown(slides_data, pdf_path=pdf_path)
        mode_text = "开启" if slide_images_enabled else "关闭（默认）"
        lines = [
            f"=== 课堂投影 PPT 截图 (sub_id={sub_id}, 共 {len(slides_data)} 页) ===",
            f"讲义插图模式: {mode_text}"
            "（dsh 设置 embedSlideImages / 环境变量 ZJU_EMBED_SLIDES）",
            "说明: 智云接口返回的是投影画面截图，不是文字层；"
            "未下载或模型不能看图时，请只用字幕与本地课件生成讲义。",
        ]
        if download and not slide_images_enabled:
            lines.append("本次按显式 download=true 执行。")
        elif slide_images_enabled and not download:
            lines.append("本次 download=false，未下载截图。")
        if download_note:
            lines.append(download_note)
        if note_example:
            lines.append(f"引用示例: {note_example}（讲义在子目录时按层级补 ../）")
        else:
            example_slide = next(
                (slide for slide in slides_data if slide.get("workspace_rel")),
                None,
            )
            if example_slide:
                page = example_slide.get("page") or 1
                relative = example_slide["workspace_rel"]
                lines.append(
                    f"引用示例: ![第 {page} 页]({relative})"
                    "（讲义在子目录时按层级补 ../）"
                )
        if diagnostics:
            lines.append("采集提示:")
            lines.extend(f"- {item}" for item in diagnostics)
        return "\n".join(lines) + "\n\n" + md

    if name == "zju_extract_courseware":
        file_path = str(arguments.get("file_path", ""))
        max_chars = arguments.get("max_chars") or 10000
        resolved, tried = resolve_path(file_path)
        if resolved is None:
            return f"错误: 找不到课件文件: {file_path}{describe_attempts(tried)}"
        try:
            text = extract_courseware_text(resolved, max_chars)
        except CoursewareError as exc:
            return f"错误: {exc}"
        return (
            f"=== 课件文件提取成功 ({os.path.basename(resolved)}) ===\n"
            f"提取字数: {len(text)} 字符\n\n"
            f"{text}"
        )

    if name == "zju_get_video_url":
        parsed = parse_lecture_url(str(arguments.get("url_or_sub_id", "")))
        sub_id = parsed["sub_id"]
        course_id = arguments.get("course_id") or parsed.get("course_id", "")
        tenant = arguments.get("tenant_code") or parsed.get("tenant_code") or DEFAULT_TENANT

        cookie, cookie_error, _source, reason = _resolve_cookie()
        if not cookie:
            return _cookie_failure_text("视频 MP4 直链", reason, cookie_error)

        video_diagnostics: List[str] = []
        mp4_url = fetch_video_url(
            course_id, sub_id, tenant, cookie, diagnostics=video_diagnostics
        )
        if not mp4_url:
            reason = "\n".join(f"- {item}" for item in video_diagnostics) or "- 未获得具体原因"
            return (
                f"未能获取到 MP4 视频直链 (sub_id={sub_id}, course_id={course_id})\n"
                f"诊断：\n{reason}"
            )

        return json.dumps(
            {"sub_id": sub_id, "course_id": course_id, "video_url": mp4_url},
            ensure_ascii=False,
            indent=2,
        )

    if name == "zju_check_note":
        file_path = str(arguments.get("file_path", "")).strip()
        if not file_path:
            raise ValueError("zju_check_note 需要 file_path 参数")
        resolved, tried = resolve_path(file_path)
        if resolved is None:
            return f"错误: 找不到讲义文件: {file_path}{describe_attempts(tried)}"
        file_path = resolved
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

        max_samples = _clamped_max_samples(arguments.get("max_samples"), 3)
        applied = []
        backup_path = ""
        if arguments.get("fix"):
            fixed_text, applied = fix_markdown(note_text)
            if fixed_text != note_text:
                try:
                    backup_path = write_with_backup(file_path, fixed_text)
                except OSError as exc:
                    hint = (
                        f"备份在 {backup_path}"
                        if backup_path and os.path.exists(backup_path)
                        else "备份未生成"
                    )
                    return f"错误: 回写讲义文件失败（原文件未改动，{hint}）: {exc}"
                note_text = fixed_text

        report = format_report(
            os.path.basename(file_path), check_markdown(note_text), max_samples
        )
        if applied:
            applied_block = "\n".join(f"- {item}" for item in applied)
            if backup_path:
                applied_block += f"\n- 原文件已备份到 {backup_path}"
            report = f"=== 已自动修复 ===\n{applied_block}\n\n{report}"
        return report

    if name == "zju_write_note":
        sub_id = str(arguments.get("sub_id", "")).strip()
        content = arguments.get("content")
        if not sub_id:
            raise ValueError("zju_write_note 需要 sub_id 参数")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("zju_write_note 需要非空的 content 参数（讲义 Markdown 全文）")
        if len(content) > MAX_NOTE_CHARS:
            return (
                f"错误: 讲义内容 {len(content)} 字符，超过 {MAX_NOTE_CHARS} 字符上限；"
                "请分批写入或检查是否误传了别的内容。"
            )

        target, target_error = note_target(
            sub_id,
            str(arguments.get("slug") or ""),
            arguments.get("directory"),
            str(arguments.get("name") or ""),
        )
        if target_error:
            return f"错误: {target_error}"

        overwrite = bool(arguments.get("overwrite"))
        already = os.path.exists(target)
        if already and not overwrite:
            # Silent overwrite is how one lecture's note ate the previous one's:
            # hand the decision back to the caller instead of guessing.
            stat = os.stat(target)
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
            return (
                "=== 未写入：同名讲义已存在 ===\n"
                f"路径: {target}\n"
                f"大小: {stat.st_size} 字节 | 修改时间: {stamp}\n"
                "为避免静默覆盖历史讲义，本次没有写入。请二选一：\n"
                "- 换一个名字：传不同的 name（上课日期 + 本节主题），文件名会随之变化；\n"
                "- 确认覆盖：再次调用并传 overwrite=true（原文件会先备份到备份目录）。"
            )

        fixed_text = content
        applied: List[str] = []
        if arguments.get("fix", True):
            fixed_text, applied = fix_markdown(content)
        try:
            if already:
                backup_path = write_with_backup(target, fixed_text)
            else:
                backup_path = ""
                write_atomic(target, fixed_text)
        except OSError as exc:
            return f"错误: 写入讲义文件失败: {target}（{exc}）"

        max_samples = _clamped_max_samples(arguments.get("max_samples"), 3)
        report = format_report(
            os.path.basename(target), check_markdown(fixed_text), max_samples
        )
        header = [
            "=== 已写入讲义 ===",
            f"路径: {target}",
            f"字数: {len(fixed_text)} 字符",
        ]
        if not str(arguments.get("name") or "").strip():
            header.append(
                "提示: 本次用的是回退文件名。建议下次传 name=知识总结-<上课日期>-<课程简称>-<本节主题>，"
                "文件名带日期与内容更利于区分不同讲次。"
            )
        if applied:
            header.append("自动修复:")
            header.extend(f"- {item}" for item in applied)
        if backup_path:
            header.append(f"原文件已备份到 {backup_path}")
        return "\n".join(header) + "\n\n" + report

    if name == "zju_read_browser_cookie":
        cookie, error, source, reason = _resolve_cookie()
        if not cookie:
            return _cookie_failure_text("登录 Cookie", reason, error, verb="能读取到")

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
