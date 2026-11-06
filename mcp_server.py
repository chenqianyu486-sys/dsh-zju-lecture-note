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
import re
import shutil
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from zju_lecture.browser_login import (
    LoginError,
    clear_session,
    load_session_cookie,
    login_available,
    open_login_window,
    session_summary,
)
from zju_lecture.client import (
    TranscriptAuthError,
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
    is_inside_workspace,
    note_target,
    primary_workspace,
    require_workspace_path,
    resolve_path,
)
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
    COURSEWARE_EXTENSIONS,
    NOTE_EXTENSIONS,
    REDACTOR,
    LocalFileError,
    describe_cookie,
    guard_local_file,
    sanitize_cookie_header,
)
from zju_lecture.study_notes import (
    KNOT_BUDGET_PER_SECTION,
    KNOT_RATIO_TARGET,
    KNOT_RATIO_TOO_MANY,
    StudyNotesError,
    apply_draft_edits,
    build_draft,
    compile_project,
    find_typst,
    render_typst,
)

SERVER_NAME = "zju-lecture-mcp"
SERVER_VERSION = "2.2.6"
DEFAULT_TENANT = "112"
DEFAULT_DOMAIN = "classroom.zju.edu.cn"

#: Upper bound for one note passed to ``zju_write_note`` (bytes are larger for
#: Chinese, but a lecture note never legitimately exceeds this).
MAX_NOTE_CHARS = 2 * 1024 * 1024

#: Local, host-controlled cookie sources. Nothing here is model-supplied.
COOKIE_ENV = "ZJU_COOKIE"
COOKIE_FILE_ENV = "ZJU_COOKIE_FILE"
_MAX_COOKIE_FILE_BYTES = 64 * 1024

#: Sub-switch of the projection pipeline: download projected-slide screenshots
#: and reference them in the note. Off by default because it adds download
#: time and vision tokens.
EMBED_SLIDES_ENV = "ZJU_EMBED_SLIDES"
#: Master switch for the optional projection pipeline. The dsh plugin always
#: exports 0/1 from its own setting; plain MCP hosts keep the pre-1.5.1
#: behaviour (enabled) unless they explicitly set 0.
SLIDES_ENABLED_ENV = "ZJU_ENABLE_SLIDES"
#: Optional fill-in study-note workflow (``zju_build_study_notes``). dsh gates
#: it from its own setting; plain MCP hosts keep the previous behaviour.
STUDY_NOTES_ENABLED_ENV = "ZJU_ENABLE_STUDY_NOTES"
#: Login helpers (``zju_get_video_url`` / ``zju_read_browser_cookie``). They
#: are independent of the projection module: turning slides off must not
#: silently remove the ability to resolve a video URL, and turning these off
#: must not affect slides (which resolve the cookie themselves).
LOGIN_TOOLS_ENABLED_ENV = "ZJU_ENABLE_LOGIN_TOOLS"
#: Automatic typesetting of a written note into a reading PDF. Default off
#: for plain MCP hosts (Typst is optional and may be absent); the dsh plugin
#: sets 1 from its own setting.
RENDER_PDF_ENV = "ZJU_RENDER_PDF"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})

#: Tools that depend on an optional module. They are left out of
#: ``tools/list`` when the feature is off, so a transcript-only host never
#: sees a tool it cannot use (or its login/cookie requirement).
SLIDES_TOOL_NAMES = ("zju_fetch_slides",)
STUDY_TOOL_NAMES = ("zju_build_study_notes",)
LOGIN_TOOL_NAMES = ("zju_get_video_url", "zju_read_browser_cookie")


class SlidesDisabledError(Exception):
    """Raised when a projection tool is called while the feature is off."""


class StudyNotesDisabledError(Exception):
    """Raised when the fill-in study-note tool is called while it is off."""


class LoginToolsDisabledError(Exception):
    """Raised when a login helper is called while the login module is off."""


def _env_flag(name: str, default: bool) -> bool:
    """Read one 0/1-style environment switch, falling back to ``default``."""
    raw = str(os.environ.get(name, "")).strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return default


def slides_enabled() -> bool:
    """Whether the optional projection (PPT screenshot) pipeline is enabled.

    The transcript pipeline is always available and never consults this
    switch; only ``zju_fetch_slides`` and the slide-image embedding are gated.
    """
    return _env_flag(SLIDES_ENABLED_ENV, True)


def study_notes_enabled() -> bool:
    """Whether the optional fill-in study-note workflow is enabled."""
    return _env_flag(STUDY_NOTES_ENABLED_ENV, True)


def login_tools_enabled() -> bool:
    """Whether the login helper tools are registered."""
    return _env_flag(LOGIN_TOOLS_ENABLED_ENV, True)


def render_pdf_enabled() -> bool:
    """Whether writing a note should also try to typeset a reading PDF."""
    return _env_flag(RENDER_PDF_ENV, False)


def available_tools() -> List[Dict[str, Any]]:
    """TOOLS after feature gates, as advertised by ``tools/list``."""
    hidden = set()
    if not slides_enabled():
        hidden.update(SLIDES_TOOL_NAMES)
    if not study_notes_enabled():
        hidden.update(STUDY_TOOL_NAMES)
    if not login_tools_enabled():
        hidden.update(LOGIN_TOOL_NAMES)
    if not hidden:
        return TOOLS
    return [tool for tool in TOOLS if tool["name"] not in hidden]


def embed_slides_enabled() -> bool:
    """Whether the host asked for projected-slide images in the note.

    This is the note-illustration sub-switch only; the projection pipeline
    itself is gated by :func:`slides_enabled` at the call sites.
    """
    return str(os.environ.get(EMBED_SLIDES_ENV, "")).strip().lower() in _TRUE_VALUES


def slide_image_mode_text() -> str:
    """One sentence describing the note-illustration mode for this process."""
    if not slides_enabled():
        return "投影抓取已关闭，讲义只使用字幕与本地课件。"
    if embed_slides_enabled():
        return (
            "讲义插图模式：开启。写讲义前默认抓一次投影（整节课只抓一次），"
            "从返回的截图里挑 3–8 张关键页，按讲义所在目录的相对路径插入 Markdown；"
            "模型不能查看本地图片时，只在文末列截图索引，不要臆造截图内容。"
        )
    return (
        "讲义插图模式：关闭（默认，节省下载时间与 token）。"
        "用户明确要求插图时再调用 zju_fetch_slides(download=true)。"
    )


def _pdf_mode_text() -> str:
    if render_pdf_enabled():
        return (
            "zju_write_note 写入后会自动把讲义排成同名 PDF（需要本机 Typst；"
            "ZJU_RENDER_PDF=0 可关闭）；无需再调用别的工具来出 PDF。"
        )
    return "讲义 PDF 自动排版已关闭（ZJU_RENDER_PDF=0）；需要时在插件设置里打开。"


def server_instructions() -> str:
    """MCP initialize instructions, reflecting the current feature gates."""
    parts = [
        "提供浙大智云课堂（classroom.zju.edu.cn）回放的语音字幕与课件文本提取。"
        "字幕先匿名请求；401/403 时自动使用本机登录态重试一次，无需开启登录辅助工具。"
        "本机没有可用登录态、或登录态已失效时，调用 zju_login(url=<这节课链接>) "
        "打开独立登录窗口：用户只需在窗口里正常登录，窗口会自动关闭并把登录态安全保存在本机；"
        "不要让用户打开开发者工具复制 Cookie，也不要索要 Cookie / 密码。",
        "登录态来源顺序：进程缓存 → ZJU_COOKIE → ZJU_COOKIE_FILE → zju_login 保存的本机登录态 → 本机 Edge。"
        "ZJU_COOKIE / ZJU_COOKIE_FILE 是高级兜底，存在且损坏时会挡住 zju_login。",
        "主链路：把链接或 sub_id 直接交给 zju_fetch_transcript（默认 per_minute；"
        "长课用 chunked；同一节课只抓一次，per_segment 仅在确实需要秒级时间戳时用）"
        "→ 可选 zju_extract_courseware → zju_write_note（自动命名、拒绝静默覆盖、"
        "写前修正、写后校验）。zju_write_note 已包含检查，不要为同一份讲义再调 "
        "zju_check_note；它只用于修复已有文件。相对路径按 ZJU_WORKSPACE 解析。"
        + _pdf_mode_text(),
        "讲义默认按「复习版」写：每节保留 [HH:MM]；老师讲过的例题整理成"
        "「题目 → 切入点 → 关键步骤 → 易错点」，本节没有例题就写「本节无例题」；"
        "文末给 3–5 道自测题（答案用 <details> 折叠）与 5–10 条考点预测。",
    ]
    if slides_enabled():
        parts.append(
            "投影截图（可下载并合成 PDF）需要登录态（Cookie 需含 _token）；"
            "投影抓取可用 ZJU_ENABLE_SLIDES=0 关闭。"
        )
    else:
        parts.append(
            "投影抓取已关闭（ZJU_ENABLE_SLIDES=0）：不为投影读取登录态、不下载投影截图，"
            "zju_fetch_slides 不在工具列表里。需要时在 dsh 插件设置里打开"
            "「启用 PPT 投影抓取」（enableSlides），或设置 ZJU_ENABLE_SLIDES=1 后重启。"
        )
    if study_notes_enabled():
        parts.append(
            "填空笔记已开启：写完讲义后默认再出一份填空版（用户只要 Markdown/PDF 时跳过）——"
            "zju_build_study_notes 先 mode=draft 生成填空底稿（你补内容），再 mode=compile 编译成 PDF。"
        )
    else:
        parts.append(
            "填空笔记已关闭（ZJU_ENABLE_STUDY_NOTES=0）：zju_build_study_notes 不在工具列表里；"
            "普通讲义 PDF 不受影响。"
        )
    if login_tools_enabled():
        parts.append(
            "登录辅助工具已开启：视频直链与浏览器登录态工具已注册；"
            "字幕鉴权属于核心链路，匿名被拒时会自行读取本机登录态，不依赖本开关。"
        )
    else:
        parts.append(
            "登录辅助工具已关闭（ZJU_ENABLE_LOGIN_TOOLS=0）：视频直链与浏览器登录态工具不注册；"
            "字幕鉴权仍由核心链路自动完成，投影抓取也自行解析登录态。"
        )
    parts.append(
        "任何工具都不接受也不回显 Cookie 明文；登录态只来自本机配置、zju_login 保存的"
        "本机登录态或本机 Edge，绝不进入对话与工具参数。"
        + slide_image_mode_text()
    )
    return "".join(parts)

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
    the session saved by ``zju_login`` → local Edge. Explicit host
    configuration wins; otherwise the one-click login window is preferred over
    the browser database because ABE can make Edge unreadable.

    The error text is actionable and never contains a cookie value. ``reason``
    is a machine-readable code (``abe`` / ``locked`` / ``no_rows`` /
    ``env_invalid`` …) so a caller can print exactly one conclusion instead of
    a list of maybes.
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

    session_cookie = load_session_cookie()
    if session_cookie:
        return _remember_cookie(session_cookie), None, "session", None

    cookie, error = read_edge_cookies(DEFAULT_DOMAIN)
    if cookie:
        return _remember_cookie(cookie), None, "edge", None
    if error is None:
        return None, f"未能从本机 Microsoft Edge 读取到 {DEFAULT_DOMAIN} 的登录 Cookie。", None, "no_credentials"
    # 只回「是什么问题」这一句：修复办法由下面的 COOKIE_FAILURE_ACTIONS 给出。
    # 以前把 ``str(error)``（message + hint）整段塞进「说明」，再跟一行
    # 「唯一可行动作」——同一句 ZJU_COOKIE_FILE 在一段 5 行的报错里出现两次，
    # 模型只能照抄给用户（实地会话 session-5415d8a5）。
    message = getattr(error, "message", "") or str(error)
    return None, message, None, error.reason


#: One concrete next step per cookie-failure reason.
#:
#: The old code pasted every possibility into one paragraph, which produced
#: messages like "请完全退出 Edge 后重试；本机已启用 ABE，退出 Edge 也无法解密"
#: — advice that contradicts itself and tells the agent nothing about which
#: path to take. Each reason now maps to exactly one action. The default is
#: the one-click login window; `ZJU_COOKIE_FILE` stays as the advanced
#: fallback for headless hosts, not as the first thing a normal user sees.
COOKIE_FAILURE_ACTIONS: Dict[str, str] = {
    "abe": "调用 zju_login 打开独立登录窗口（不要开开发者工具、不要手工配置 Cookie）；"
    "登录成功后窗口自动关闭，登录态会安全保存在本机，然后重试。",
    "locked": "调用 zju_login 打开独立登录窗口；也可以完全退出 Edge 后重试。",
    "no_rows": "调用 zju_login 在独立登录窗口里登录智云课堂，然后重试。",
    "decrypt_failed": "调用 zju_login 重新登录；不要再依赖 Edge 的 Cookie 解密。",
    "not_found": "调用 zju_login 打开独立登录窗口完成登录；不需要本机装过 Edge。",
    "db_error": "调用 zju_login 重新登录；也可以完全退出 Edge 后重试。",
    "unsupported_platform": "当前平台没有可用的图形浏览器：在宿主配置里设置 ZJU_COOKIE_FILE 兜底。",
    "keychain_denied": "调用 zju_login 打开独立登录窗口；或在钥匙串授权框选择『始终允许』。",
    "no_credentials": "调用 zju_login 打开独立登录窗口完成登录；不要向用户索要 Cookie。",
    "env_invalid": "检查或移除 ZJU_COOKIE 配置（需要一行合法的 name=value Cookie 头）；"
    "该环境变量存在时优先级最高，会挡住 zju_login。",
    "file_unreadable": "检查或移除 ZJU_COOKIE_FILE 配置（需要存在、可读、UTF-8、只含一行 Cookie 头）；"
    "该环境变量存在时优先级最高，会挡住 zju_login。",
    "session_expired": "本机保存的登录态已失效并被清除：调用 zju_login 重新登录后重试。",
    "unknown": "调用 zju_login 打开独立登录窗口重新登录后重试。",
}


def _forget_cookie(source: Optional[str]) -> None:
    """Drop an invalid session from memory and disk.

    A 401/403 from the server means the cookie is dead even though it was
    readable locally. The saved session (and the dedicated browser profile,
    which would otherwise hand the same dead cookie back) is removed so the
    next ``zju_login`` starts a real login instead of replaying it.
    """
    _COOKIE_CACHE.pop(DEFAULT_DOMAIN, None)
    if source == "session":
        try:
            clear_session(delete_profile=True)
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask the 401
            _log(f"清除失效登录态失败：{exc}")


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
            "抓取智云课堂某节课的语音识别字幕。先匿名；401/403 时自动用本机登录态重试一次。"
            "登录态只能来自本机 Edge 或 ZJU_COOKIE_FILE，不要传 Cookie。"
            "默认 per_minute 带时间戳；长课用 chunked；同一节课只抓一次，"
            "per_segment 仅在确实需要秒级时间戳时用。"
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
            "（可选投影模块）抓取智云课堂投影 PPT 截图清单。search-ppt 返回的是"
            "投影截图，不是文字层/OCR；download=true 时下载截图并合成 PDF（省略时跟随 "
            "enableSlides / embedSlideImages，即 ZJU_ENABLE_SLIDES / ZJU_EMBED_SLIDES）。"
            "需要登录态（Cookie 含 _token，由服务端本地解析，不接受也不回显 Cookie）。"
            "抓不到时返回诊断，可降级为纯字幕总结。dsh 的 enableSlides 关闭时本工具不注册。"
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
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "确认执行有副作用的操作（默认 false）。confirm=true 才批量下载截图"
                        "（最多 2000 张）到工作区并合成 PDF；否则只返回清单，不写盘"
                    ),
                    "default": False,
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
                "allow_outside_workspace": {
                    "type": "boolean",
                    "description": (
                        "是否允许读取工作区之外的课件（默认 false）。"
                        "显式设为 true 时仍拒绝凭据/浏览器数据/密钥文件，"
                        "并在结果首行标注「已读取工作区外文件」"
                    ),
                    "default": False,
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "zju_get_video_url",
        "description": (
            "解析回放视频的 MP4 直链（本地下载或 Whisper 重识别）。需要登录态；"
            "服务端自动使用缓存 / ZJU_COOKIE / 本机 Edge，不接受也不回显 Cookie。"
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
            "检查/修正已有讲义 Markdown 的公式与渲染规范（静态、不联网）。"
            "write_note 已自动检查，通常无需重复调用；只有手工改过文件时才用它修复。"
            "fix=true 自动修正机械问题并先备份；报告按问题类型聚合。"
            "pdf=true 时检查后重新排版一份同名 PDF。只处理工作区内的讲义。"
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
                "pdf": {
                    "type": "boolean",
                    "description": "检查后是否重新排版同名 PDF（默认 false；write_note 已自动排版）",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "zju_write_note",
        "description": (
            "写入讲义 Markdown：自动命名（知识总结-<日期>-<课程>-<主题>）、默认拒绝静默覆盖、"
            "写前修正公式、写后返回规范检查，并按设置自动排版同名 PDF——"
            "写文件、检查、出 PDF 一次完成。只写工作区内的 .md 文件。"
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
                "pdf": {
                    "type": "boolean",
                    "description": "写入后是否排版同名 PDF（默认跟随插件设置 renderPdf；显式 true/false 可覆盖）",
                },
            },
            "required": ["sub_id", "content"],
        },
    },
    {
        "name": "zju_login",
        "description": (
            "打开一个独立的浏览器登录窗口完成浙大登录（不接收密码，也不接收 Cookie）。"
            "用户在该窗口里正常登录后，窗口自动关闭，登录态安全保存在本机，后续字幕与投影自动复用。"
            "字幕/投影 401/403、ABE 导致 Edge Cookie 读不了、用户说「登录智云课堂」时调用。"
            "clear=true 清除本机登录态与独立登录窗口配置。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "登录后要打开的课堂链接（可选，仅接受 https 的 *.zju.edu.cn；"
                        "建议传用户给的这节课链接）"
                    ),
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "等待用户完成登录的最长秒数（默认 300，范围 30–540）",
                    "default": 300,
                },
                "clear": {
                    "type": "boolean",
                    "description": "只清除本机保存的登录态与独立登录窗口配置，不打开窗口（默认 false）",
                    "default": False,
                },
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "确认执行有副作用的操作（默认 false）。clear=true 时必须同时传 "
                        "confirm=true 才会删除登录态与浏览器配置"
                    ),
                    "default": False,
                },
            },
        },
    },
    {
        "name": "zju_read_browser_cookie",
        "description": (
            "读取本机 Edge 的 classroom.zju.edu.cn 登录态（含父域 .zju.edu.cn 的 _token）"
            "到服务端内存；只返回名称与长度，绝不回显明文，无参数。"
            "Edge 启用 ABE 时会失败；这种情况改用 zju_login。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
    },
    {
        "name": "zju_build_study_notes",
        "description": (
            "把讲义变成 scholia 填空式学习笔记（Typst → PDF）。"
            "mode=draft 生成填空底稿（你补内容）；mode=patch 用 edits 一次写回多处挖空/标记；"
            "mode=compile 编译成 out.pdf + 逐页 PNG，并报告编译错误、方框预算与改不动的数学。"
            "需要本机 Typst（≥0.13）。只写工作区内的文件。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["draft", "patch", "compile"],
                    "description": (
                        "draft=讲义转填空底稿（只搬运与改公式，不做内容判断）；"
                        "patch=按 edits 一次写回底稿（批量挖空，省掉十几次单条编辑）；"
                        "compile=底稿转 Typst 并编译成 PDF"
                    ),
                    "default": "draft",
                },
                "edits": {
                    "type": "array",
                    "description": (
                        "mode=patch 的修改列表：每项 {old, new}，old 必须在底稿里"
                        "恰好出现一次（重复时加长上下文，或加 all=true 全部替换）。"
                        "一次最多 80 条"
                    ),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "old": {"type": "string", "description": "原文（精确匹配，含标点）"},
                            "new": {"type": "string", "description": "替换成的新文本"},
                            "all": {
                                "type": "boolean",
                                "description": "原文出现多次时是否全部替换（默认 false）",
                            },
                        },
                        "required": ["old", "new"],
                    },
                },
                "note_path": {
                    "type": "string",
                    "description": "讲义 Markdown 的路径（mode=draft 必填）",
                },
                "draft_path": {
                    "type": "string",
                    "description": "填空底稿 Markdown 的路径（mode=patch / compile 必填）",
                },
                "output_dir": {
                    "type": "string",
                    "description": (
                        "输出目录，相对当前工作区（默认与源文件同目录；"
                        "源文件在工作区外时写到工作区的 notes/ 下）"
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "封面标题（mode=draft；默认取讲义的第一个一级标题）",
                },
                "subtitle": {
                    "type": "string",
                    "description": "封面副标题（mode=draft，可选）",
                },
                "author": {
                    "type": "string",
                    "description": "封面作者（mode=draft，可选）",
                },
                "date": {
                    "type": "string",
                    "description": "封面日期（mode=draft，可选，例如 2026-11-02）",
                },
                "kicker": {
                    "type": "string",
                    "description": "封面上方的小字行（mode=draft，可选，例如课程代码）",
                },
                "theme": {
                    "type": "string",
                    "enum": ["light", "dark"],
                    "description": "配色主题（mode=compile，默认 light 淡彩极简）",
                    "default": "light",
                },
                "make_png": {
                    "type": "boolean",
                    "description": (
                        "是否同时导出逐页 PNG（mode=compile，默认 true）。"
                        "knot 的内容块数量错位不会报错，只能靠看图发现，所以建议保持开启"
                    ),
                    "default": True,
                },
                "pages": {
                    "type": "string",
                    "description": "只导出指定页的 PNG，例如 1-3（mode=compile，可选）",
                },
            },
        },
    },
    {
        "name": "zju_doctor",
        "description": (
            "检查本机依赖并给出可执行结论：Python、Typst（版本 / 路径 / 来源 / 是否满足 ≥0.13）、"
            "随包中文字体与离线 Typst 包、缓存目录、登录窗口是否可用、本机是否保存了登录态；"
            "login=true 时额外验证登录态是否真的可用。"
            "install=true 时下载并校验安装 Typst"
            "（SHA256 固定，仅官方 Release；可用 ZJU_TYPST_AUTO_INSTALL=0 关闭自动安装）。"
            "PDF 失败或用户问「为什么没有 PDF」时先跑它；没有任何输出时先跑它，再调用一次 zju_login。"
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "install": {
                    "type": "boolean",
                    "description": "缺少 Typst 时是否立即下载安装（默认否；安装约 20 MB）",
                    "default": False,
                },
                "login": {
                    "type": "boolean",
                    "description": "是否读取本机登录态检查可用性（默认否；不会回显凭据）",
                    "default": False,
                },
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "确认执行有副作用的操作（默认 false）。install=true 时必须同时传 "
                        "confirm=true 才会下载安装 Typst（约 20 MB）"
                    ),
                    "default": False,
                },
            },
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


def _study_notes_output_dir(source_path: str, output_dir: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve the directory generated study-note files go into.

    An explicit ``output_dir`` wins (and must stay inside the workspace).
    Otherwise the source file's own directory is used when that directory is
    inside the workspace; a source living outside falls back to ``notes/``,
    so a new file is never written outside the workspace.
    """
    raw = str(output_dir or "").strip()
    if raw:
        return artifact_dir(raw, default="notes")
    parent = os.path.dirname(source_path)
    if parent and is_inside_workspace(parent):
        return parent, None
    return artifact_dir("", default="notes")


def _study_notes_sections(knots: List[Dict[str, Any]]) -> str:
    """Summarise knot counts per section: ``第一节 3 个；第二节 1 个``."""
    counts: Dict[str, int] = {}
    for knot in knots:
        name = str(knot.get("section") or "")
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return "无"
    return "；".join(f"{name or '(未命名)'} {count} 个" for name, count in counts.items())


def _note_cover_meta(note_path: str, note_text: str) -> Tuple[str, str]:
    """Derive the cover title/date for a reading PDF.

    The lecture note's first H1 is the title; the date comes from the file
    name (``知识总结-2026-10-28-…``) when present. Neither is guessed — an
    absent field simply stays empty.
    """
    stem = os.path.splitext(os.path.basename(note_path))[0]
    heading = re.search(r"^#\s+(.+?)\s*$", note_text, re.MULTILINE)
    fallback = re.sub(r"^知识总结-", "", stem).replace("-", " ").strip()
    title = heading.group(1).strip() if heading else (fallback or stem)
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", stem)
    return title, date_match.group(1) if date_match else ""


_LOGIN_SOURCE_LABELS = {
    "cache": "进程内缓存",
    "env": "ZJU_COOKIE",
    "file": "ZJU_COOKIE_FILE",
    "session": "zju_login 安全保存",
    "edge": "本机 Edge",
}


def _login_status_text() -> List[str]:
    """One concise login-status block for ``zju_doctor`` (never prints credential values)."""
    try:
        cookie, error, source, reason = _resolve_cookie()
    except Exception:  # noqa: BLE001 - diagnostics must never fail the doctor
        return ["登录态: 检查失败（内部错误）"]
    if cookie:
        token = extract_classroom_token(cookie)
        label = _LOGIN_SOURCE_LABELS.get(source or "", source or "未知")
        lines = [
            f"登录态: 可用（来源 {source}（{label}）；Bearer {'可用' if token else '缺失'}）",
            "  字幕匿名被拒时会自动使用；无需开启登录辅助。",
        ]
        summary = session_summary()
        if summary.get("available"):
            lines.append(
                "  本机保存的登录态: 存在"
                f"（{summary.get('cookie_count', 0)} 条 Cookie，"
                f"浏览器 {summary.get('browser') or '未知'}）"
            )
        return lines
    action = COOKIE_FAILURE_ACTIONS.get(reason or "unknown", COOKIE_FAILURE_ACTIONS["unknown"])
    lines = [f"登录态: 不可用（原因 {reason or 'unknown'}）"]
    if error:
        lines.append(f"  说明: {REDACTOR.redact(error)}")
    lines.append(f"  修复: {action}")
    available, detail = login_available()
    lines.append(
        "  登录窗口: " + ("可用（" + detail + "）" if available else "不可用（" + detail + "）")
    )
    return lines


def _doctor_report(install: bool, check_login: bool = False) -> str:
    """``zju_doctor``：依赖快照；``install`` 为真时先自举 Typst。

    ``check_login`` 默认关闭：诊断依赖不应顺带读取浏览器登录态。
    """
    from zju_lecture import deps

    auto = deps.auto_install_enabled()
    if install:
        result = deps.install(force=True)
        if not result.ok:
            return "Typst 安装未完成：\n- " + "\n- ".join(result.notes or ["原因未识别"])

    workspace = primary_workspace()
    info = deps.describe(workspace, auto_install=False)
    lines = [
        "=== 环境自检 ===",
        f"Python: {info['version']}（{info['platform']}）",
    ]

    if info["typst_ok"]:
        lines.append(
            f"Typst: {info['typst_version']} ✓（来源 {info['typst_source']}）"
        )
        lines.append(f"  路径: {info['typst_path']}")
    else:
        lines.append(f"Typst: 不可用 ✗（要求 ≥ {info['typst_min']}）")
        for note in info["typst_notes"]:
            lines.append(f"  - {note}")

    lines.append(f"  随包版本: {info['typst_bundled_version'] or '缺失'}")
    lines.append(
        "随包字体: " + ("Notes Serif SC 子集（OFL）" if info["fonts"] else "缺失")
    )
    lines.append(
        "Typst 包: " + ("已 vendor（填空笔记离线可用）" if info["packages"] else "缺失")
    )
    lines.append(f"汇编缓存: {info['compile_cache'] or '(未指定工作区)'}")
    lines.append(f"自动安装: {'开' if auto else '关'}（ZJU_TYPST_AUTO_INSTALL）")
    summary = session_summary()
    if summary.get("available"):
        saved_at = summary.get("saved_at")
        stamp = ""
        if isinstance(saved_at, (int, float)):
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(saved_at))
        lines.append(
            "本机登录态: 已保存"
            f"（{summary.get('cookie_count', 0)} 条 Cookie，浏览器 {summary.get('browser') or '未知'}"
            + (f"，保存于 {stamp}" if stamp else "")
            + "；不含账号密码）"
        )
    else:
        lines.append("本机登录态: 未保存（需要时调用 zju_login 打开独立登录窗口）")
    login_ok, login_detail = login_available()
    lines.append(
        "登录窗口: " + ("可用（" + login_detail + "）" if login_ok else "不可用（" + login_detail + "）")
    )
    if check_login:
        lines.extend(_login_status_text())
    else:
        lines.append("登录态: 未检查（字幕 401/403 时自动读取；需要时用 zju_doctor(login=true)）")
    lines.append(
        "模块: 投影=%s / 填空=%s / 登录=%s / PDF=%s（本进程启动时的设置）"
        % (
            "开" if slides_enabled() else "关",
            "开" if study_notes_enabled() else "关",
            "开" if login_tools_enabled() else "关",
            "开" if render_pdf_enabled() else "关",
        )
    )
    if info["mirror"]:
        lines.append(f"下载镜像: {info['mirror']}")
    if not info["typst_ok"]:
        lines.append("修复: 运行 zju_doctor(install=true)，或设置 ZJU_TYPST_BIN 指向已安装的 typst。")
    return "\n".join(lines)


def _render_note_pdf(note_path: str, note_text: str) -> List[str]:
    """Typeset the written note into a reading PDF; never raises.

    Returns 0–2 short lines for the tool result. A missing Typst or a
    rendering error must not turn a successful Markdown write into a failure:
    the Markdown is the deliverable, the PDF is an enhancement.
    """
    if not is_inside_workspace(note_path):
        return ["PDF 跳过: 讲义在工作区外，未写 PDF（避免越界写入）"]
    title, date = _note_cover_meta(note_path, note_text)
    try:
        from zju_lecture.handout import compile_handout_file

        result = compile_handout_file(
            note_path,
            note_text,
            title=title,
            date=date,
            workspace_root=primary_workspace(),
        )
    except Exception as exc:  # noqa: BLE001 - PDF is an enhancement
        return [f"PDF 跳过: {exc}"]
    if result.ok:
        pages = f"（{result.pages} 页）" if result.pages else ""
        return [f"PDF: {result.pdf_path}{pages}"]
    detail = "；".join(result.errors[:2]) or "未知原因"
    if "找不到 typst" in detail:
        # Keep the common "Typst is not installed" case to one short line:
        # this string is paid on every note write while the feature is on.
        detail = "未找到 typst（Markdown 已保存；运行 zju_doctor(install=true) 自动安装，或在设置里关 renderPdf）"
    if len(detail) > 220:
        detail = detail[:219] + "…"
    # 这是「同一份讲义要不要再查一次」的唯一例外：上面报的是渲染错误，
    # 不改文件永远好不了。给一句可执行的下一步，Agent 就不必自己猜。
    return [
        f"PDF 跳过: {detail}",
        "Markdown 已写好；按上面的错误改掉对应公式后，调用 zju_check_note(pdf=true) 重排一次。",
    ]


def _patch_draft(arguments: Dict[str, Any]) -> str:
    """``mode=patch``：按 ``edits`` 一次写回底稿（批量挖空 / 补标记）。"""
    draft_path = str(arguments.get("draft_path") or "").strip()
    if not draft_path:
        return "错误: mode=patch 需要 draft_path（填空底稿的路径）"
    raw_edits = arguments.get("edits")
    if not isinstance(raw_edits, list) or not raw_edits:
        return "错误: mode=patch 需要非空的 edits（每项 {old, new}）"

    resolved, path_error = require_workspace_path(
        draft_path, extensions=NOTE_EXTENSIONS, kind="填空底稿", write=True
    )
    if path_error:
        return f"错误: {path_error}"
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            draft_text = handle.read()
    except UnicodeDecodeError:
        return f"错误: 填空底稿不是 UTF-8 编码: {resolved}"
    except OSError as exc:
        return f"错误: 读取填空底稿失败: {exc}"

    try:
        result = apply_draft_edits(draft_text, raw_edits)
    except StudyNotesError as exc:
        return f"错误: {exc}"

    if result.applied:
        try:
            write_atomic(resolved, result.text)
        except OSError as exc:
            return f"错误: 写入填空底稿失败: {resolved}（{exc}）"

    summary = f"应用: {result.applied}/{len(raw_edits)} 处"
    if result.skipped:
        summary += f"（跳过 {result.skipped} 处 old 与 new 相同）"
    lines = ["=== 已修改填空底稿 ===", f"路径: {resolved}", summary]
    if result.failures:
        lines.append("")
        lines.append(f"未应用 {len(result.failures)} 处:")
        lines.extend(f"- {item}" for item in result.failures[:12])
        if len(result.failures) > 12:
            lines.append(f"- …另有 {len(result.failures) - 12} 处")
        lines.append("")
        lines.append("已应用的部分已经写回文件，不必重发；修正上面几条后再 compile。")
        lines.append(
            f'下一步: zju_build_study_notes(mode="compile", draft_path="{resolved}")'
        )
    else:
        lines.append(
            f'下一步: zju_build_study_notes(mode="compile", draft_path="{resolved}")'
        )
    return "\n".join(lines)


def _build_study_notes(arguments: Dict[str, Any]) -> str:
    """Handle ``zju_build_study_notes``: 讲义 → 填空底稿 → Typst → PDF."""
    mode = str(arguments.get("mode") or "draft").strip().lower()
    if mode not in ("draft", "patch", "compile"):
        return "错误: mode 只能是 draft / patch / compile"

    if mode == "patch":
        return _patch_draft(arguments)

    if mode == "draft":
        note_path = str(arguments.get("note_path") or "").strip()
        if not note_path:
            return "错误: mode=draft 需要 note_path（讲义 Markdown 的路径）"
        resolved, tried = resolve_path(note_path)
        if resolved is None:
            return f"错误: 找不到讲义文件: {note_path}{describe_attempts(tried)}"
        try:
            resolved = guard_local_file(resolved, NOTE_EXTENSIONS, kind="讲义文件")
        except LocalFileError as exc:
            return f"错误: {exc}"
        try:
            with open(resolved, "r", encoding="utf-8") as handle:
                note_text = handle.read()
        except UnicodeDecodeError:
            return f"错误: 讲义文件不是 UTF-8 编码: {resolved}"
        except OSError as exc:
            return f"错误: 读取讲义文件失败: {exc}"

        draft = build_draft(
            note_text,
            title=str(arguments.get("title") or ""),
            subtitle=str(arguments.get("subtitle") or ""),
            author=str(arguments.get("author") or ""),
            date=str(arguments.get("date") or ""),
            kicker=str(arguments.get("kicker") or ""),
        )

        target_dir, target_error = _study_notes_output_dir(
            resolved, str(arguments.get("output_dir") or "")
        )
        if target_error:
            return f"错误: {target_error}"
        stem = os.path.splitext(os.path.basename(resolved))[0]
        target = os.path.join(target_dir, f"{stem}-填空底稿.md")
        try:
            write_atomic(target, draft.text)
        except OSError as exc:
            return f"错误: 写入填空底稿失败: {target}（{exc}）"

        lines = [
            "=== 已生成填空底稿 ===",
            f"路径: {target}",
            f"来源: {resolved} | 章节: {draft.sections} | 字数: {len(draft.text)}",
            "",
            "底稿已搬运完成：按内容补 [直觉]/[练习]/[边注]（可选，不需要就别加）"
            "与正文里的 ____ 挖空；[定义]/[定理]/[证明] 只在「后面会被回引」时才用"
            f"（每节框合计 ≤ {KNOT_BUDGET_PER_SECTION} 个），其余写成普通段落。",
            "公式直接写 LaTeX，工具会转成 Typst；转不动的会点名。",
            "挖空别一处一处改：把全部 {old, new} 交给 "
            'zju_build_study_notes(mode="patch", draft_path=…, edits=[…]) 一次写回。',
            f'下一步: zju_build_study_notes(mode="compile", draft_path="{target}")',
        ]
        if draft.warnings:
            lines.append("")
            lines.append("无法机械转换的数学片段（请手工改）:")
            lines.extend(f"- {item}" for item in sorted(set(draft.warnings))[:10])
        return "\n".join(lines)

    draft_path = str(arguments.get("draft_path") or "").strip()
    if not draft_path:
        return "错误: mode=compile 需要 draft_path（填空底稿的路径）"
    resolved, tried = resolve_path(draft_path)
    if resolved is None:
        return f"错误: 找不到填空底稿: {draft_path}{describe_attempts(tried)}"
    try:
        resolved = guard_local_file(resolved, NOTE_EXTENSIONS, kind="填空底稿")
    except LocalFileError as exc:
        return f"错误: {exc}"
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            draft_text = handle.read()
    except UnicodeDecodeError:
        return f"错误: 填空底稿不是 UTF-8 编码: {resolved}"
    except OSError as exc:
        return f"错误: 读取填空底稿失败: {exc}"

    theme = str(arguments.get("theme") or "light").strip().lower()
    try:
        rendered = render_typst(draft_text, theme=theme)
    except StudyNotesError as exc:
        return f"错误: {exc}"

    target_dir, target_error = _study_notes_output_dir(
        resolved, str(arguments.get("output_dir") or "")
    )
    if target_error:
        return f"错误: {target_error}"
    stem = os.path.splitext(os.path.basename(resolved))[0]
    project_dir = os.path.join(target_dir, f"{stem}-typst")

    try:
        result = compile_project(
            project_dir,
            rendered.typst,
            make_png=bool(arguments.get("make_png", True)),
            pages=str(arguments.get("pages") or "").strip(),
        )
    except StudyNotesError as exc:
        return f"错误: {exc}"

    lines = [
        "=== 填空笔记编译结果 ===",
        f"主题: {'淡彩极简（light）' if theme == 'light' else '深色（dark）'}",
        f"底稿: {resolved}",
        f"项目目录: {project_dir}",
        "",
        "=== 格式规范检查（正文优先，框框克制）===",
        f"正文段落: {rendered.paragraphs} | 方框: {rendered.knot_count} | "
        f"方框:正文 = {rendered.ratio_text()}（1:{KNOT_RATIO_TARGET} 以内较稳，"
        f"超过 1:{KNOT_RATIO_TOO_MANY} 判为滥用）",
        f"逐节方框: {_study_notes_sections(rendered.knots)}（每节上限 {KNOT_BUDGET_PER_SECTION} 个）",
        "装置使用: "
        + (", ".join(f"{name} {count}" for name, count in sorted(rendered.devices.items())) or "无"),
        "格式规范: skills/scholia-notes/references/format-spec.md（规范性文件）",
    ]
    if result.ok:
        # Typst 工程目录里的 `out.pdf` 不是「交付物位置」：讲义链路的 PDF
        # 一直和 .md 同目录，填空笔记却落在 `<stem>-typst/out.pdf` 里，
        # Agent 每次都得再 `cp` 一次才交得出来。这里直接放一份到同目录。
        #
        # 命名要避开**阅读版**那份 `<讲义名>.pdf`：自动生成的底稿叫
        # `<讲义名>-填空底稿.md`，去掉后缀正好等于讲义名，直接落 `<stem>.pdf`
        # 会把刚排好的阅读版 PDF 覆盖掉（实测覆盖过）。所以自动底稿统一叫
        # `<讲义名>-填空.pdf`；手写底稿（如 `填空笔记-XXX.md`）保持同名。
        deliverable_pdf = result.pdf_path
        if stem.endswith("-填空底稿"):
            public_stem = stem[: -len("-填空底稿")] + "-填空"
        else:
            public_stem = stem
        sibling = os.path.join(target_dir, f"{public_stem}.pdf")
        try:
            if os.path.abspath(sibling) != os.path.abspath(result.pdf_path):
                shutil.copyfile(result.pdf_path, sibling)
                deliverable_pdf = sibling
        except OSError:
            pass
        lines.append(f"PDF: {deliverable_pdf}")
        if deliverable_pdf != result.pdf_path:
            lines.append(f"Typst 工程: {project_dir}（out.pdf 是同一份）")
        if result.png_paths:
            names = ", ".join(os.path.basename(path) for path in result.png_paths)
            lines.append("逐页 PNG: " + names)
            # 直接给一条完整路径：Agent 就能把这张图原样交给看图工具，
            # 不必再 glob 一次去拼目录（实地会话为此多花了一次调用）。
            lines.append("例（可直接看）: " + result.png_paths[0])
            lines.append(
                "请抽查 PNG：knot 内容块错位不会让编译报错（退出码仍是 0）。"
                "只看与内容块/图相关的页，不必逐页全看。"
            )
    else:
        lines.append("编译失败，没有产出 PDF。")
    if rendered.warnings:
        lines.append("")
        lines.append("警告:")
        lines.extend(f"- {item}" for item in rendered.warnings)
    if result.errors:
        lines.append("")
        lines.append("错误:")
        lines.extend(f"- {item}" for item in result.errors)
    if result.warnings:
        lines.append("")
        lines.append("编译告警:")
        lines.extend(f"- {item}" for item in result.warnings[:20])
    return "\n".join(lines)


def _ensure_tool_enabled(name: str) -> None:
    """Explain a gated tool call instead of silently treating it as unknown."""
    if name in STUDY_TOOL_NAMES and not study_notes_enabled():
        raise StudyNotesDisabledError(
            "填空笔记未启用（插件设置 enableStudyNotes=false / ZJU_ENABLE_STUDY_NOTES=0）："
            "本次不注册 zju_build_study_notes。需要时在 dsh 插件设置里打开"
            "「填空式学习笔记」，或给 MCP server 设置 ZJU_ENABLE_STUDY_NOTES=1 后重启。"
        )
    if name in LOGIN_TOOL_NAMES and not login_tools_enabled():
        raise LoginToolsDisabledError(
            "登录辅助工具未启用（插件设置 enableLoginTools=false / ZJU_ENABLE_LOGIN_TOOLS=0）："
            "本次不注册 zju_get_video_url / zju_read_browser_cookie。"
            "需要时在 dsh 插件设置里打开「登录辅助工具」，"
            "或给 MCP server 设置 ZJU_ENABLE_LOGIN_TOOLS=1 后重启。"
        )


def _dispatch_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Execute the tool function and return the raw response payload."""
    _ensure_tool_enabled(name)

    if name == "zju_doctor":
        install = bool(arguments.get("install"))
        if install and arguments.get("confirm") is not True:
            return (
                "该操作会下载并安装 Typst（约 20 MB，按固定 SHA256 校验）；"
                "确认后以 confirm=true 重试。只想查看依赖状态时不要传 install=true。"
            )
        return _doctor_report(install, bool(arguments.get("login")))

    if name == "zju_parse_url":
        parsed = parse_lecture_url(str(arguments.get("url", "")))
        return json.dumps(parsed, ensure_ascii=False, indent=2)

    if name == "zju_login":
        if arguments.get("clear"):
            if arguments.get("confirm") is not True:
                return (
                    "该操作会删除本机保存的登录态与独立登录窗口的浏览器配置；"
                    "确认后以 confirm=true 重试。只想登录时不要传 clear=true。"
                )
            result = clear_session(delete_profile=True)
            _COOKIE_CACHE.pop(DEFAULT_DOMAIN, None)
            lines = [
                "已清除本机保存的登录态。"
                if result.get("session_removed")
                else "本机没有保存的登录态。"
            ]
            if result.get("profile_removed"):
                lines.append("独立登录窗口的浏览器配置也已删除。")
            if result.get("profile_error"):
                lines.append(
                    "独立登录窗口配置未能删除："
                    f"{REDACTOR.redact(result['profile_error'])}。"
                    "请先关闭该登录窗口，再重试清除。"
                )
            return "\n".join(lines)

        timeout = arguments.get("timeout_seconds") or 300
        try:
            result = open_login_window(str(arguments.get("url") or ""), timeout)
        except LoginError as exc:
            raise ZJUAPIError(
                f"登录未完成（原因: {exc.reason}）。\n"
                f"说明: {REDACTOR.redact(exc.message)}\n"
                f"下一步: {exc.hint or '请重试一次。'}"
            ) from exc
        _remember_cookie(result["cookie"])
        lines = [
            "登录成功，已读取本机登录态。",
            f"- 浏览器: {result['browser']}",
            f"- Cookie: {len(result['names'])} 条（含 _token，值不回显）",
            f"- 用时: {result['elapsed']} 秒",
        ]
        if result.get("saved"):
            lines.append(
                f"- 保存: 已安全保存到 {result['saved_path']}"
                "（仅当前系统用户可解密；不包含账号密码）"
            )
        else:
            lines.append(
                "- 保存: 未落盘（"
                f"{REDACTOR.redact(result.get('save_error') or '未知原因')}）；"
                "本次会话仍可用，但重启后需要重新登录"
            )
        lines.append("现在可以重试字幕或投影抓取，不需要再操作浏览器。")
        return "\n".join(lines)

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

        try:
            raw_segments = fetch_transcript(sub_id, tenant)
        except TranscriptAuthError as exc:
            # 字幕鉴权属于核心链路，不依赖「登录辅助」工具开关：用户默认安装
            # 即可使用。只有匿名请求确实被拒绝时才读取本机登录态。
            cookie, cookie_error, source, reason = _resolve_cookie()
            if not cookie:
                raise ZJUAPIError(
                    f"{exc}\n"
                    + _cookie_failure_text(
                        "语音字幕",
                        reason,
                        cookie_error,
                        degrade_hint=(
                            "字幕匿名请求被拒绝；插件只在这一步读取本机登录态。"
                            "需要登录时调用 zju_login(url=<这节课链接>) 打开独立登录窗口，"
                            "不要让用户开开发者工具、手工配置 Cookie，也不要把 Cookie 贴进对话。"
                        ),
                    )
                ) from exc
            try:
                raw_segments = fetch_transcript(sub_id, tenant, cookie=cookie)
            except TranscriptAuthError as auth_exc:
                _forget_cookie(source)
                session_note = (
                    "已清除本机保存的登录态；请调用 zju_login 重新登录后重试。"
                    if source == "session"
                    else "请调用 zju_login 重新登录后重试。"
                )
                raise ZJUAPIError(
                    f"字幕携带本机登录态（来源 {source}）后仍返回 HTTP {auth_exc.status}，"
                    f"已停止重试。{session_note}"
                    "若登录后仍失败，请确认该账号在官网能查看同一节课；"
                    "不能仅凭此错误断定是校园网限制。"
                ) from auth_exc
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
        if not slides_enabled():
            raise SlidesDisabledError(
                "PPT 投影抓取未启用（ZJU_ENABLE_SLIDES=0）：本进程不为投影读取登录态、"
                "不下载投影截图。\n"
                "需要投影截图时：dsh 插件设置里打开「启用 PPT 投影抓取」（enableSlides），"
                "或给 MCP server 设置环境变量 ZJU_ENABLE_SLIDES=1 后重启；"
                "不需要时直接继续用 zju_fetch_transcript 的字幕生成讲义即可。"
            )
        # Imported lazily so a transcript-only process never loads the
        # screenshot/PDF pipeline (and its auth surface) at all.
        from zju_lecture.slides import build_slides_pdf, download_slides

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

        if download and arguments.get("confirm") is not True:
            return (
                "该操作会把投影截图（最多 2000 张）下载到工作区并合成 PDF；"
                "确认后以 confirm=true 重试。只想查看截图清单时传 download=false。"
            )

        cookie, cookie_error, source, reason = _resolve_cookie()
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
            auth_failed = any(
                marker in item
                for item in diagnostics
                for marker in ("HTTP 401", "HTTP 403", "未解析到 _token", "缺少 _token")
            )
            if auth_failed:
                _forget_cookie(source)
                return _cookie_failure_text(
                    "PPT 记录",
                    "session_expired" if source == "session" else "no_credentials",
                    "投影接口拒绝了当前登录态，或 Cookie 中没有可用的 _token。",
                    degrade_hint="（流水线可平滑降级：没有 PPT 也能仅凭语音字幕生成讲义。）",
                )
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
        allow_outside = arguments.get("allow_outside_workspace") is True
        outside_note = ""
        if allow_outside:
            # 显式开关：仍然走同一套扩展名/凭据防护，只是不要求在工作区内。
            resolved, tried = resolve_path(file_path)
            if resolved is None:
                return f"错误: 找不到课件文件: {file_path}{describe_attempts(tried)}"
            try:
                resolved = guard_local_file(resolved, COURSEWARE_EXTENSIONS, kind="课件文件")
            except LocalFileError as exc:
                return f"错误: {exc}"
            if not is_inside_workspace(resolved):
                outside_note = f"已读取工作区外文件: {resolved}\n"
        else:
            resolved, path_error = require_workspace_path(
                file_path, extensions=COURSEWARE_EXTENSIONS, kind="课件文件"
            )
            if path_error:
                return f"错误: {path_error}"
        try:
            text = extract_courseware_text(resolved, max_chars)
        except CoursewareError as exc:
            return f"错误: {exc}"
        return (
            outside_note
            + f"=== 课件文件提取成功 ({os.path.basename(resolved)}) ===\n"
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
        wants_fix = arguments.get("fix") is True
        file_path, path_error = require_workspace_path(
            file_path, extensions=NOTE_EXTENSIONS, kind="讲义文件", write=wants_fix
        )
        if path_error:
            return f"错误: {path_error}"
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
        if wants_fix:
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
        if arguments.get("pdf") is True:
            report = report + "\n\n" + "\n".join(_render_note_pdf(file_path, note_text))
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
        pdf_override = arguments.get("pdf")
        should_pdf = render_pdf_enabled() if pdf_override is None else bool(pdf_override)
        if should_pdf:
            header.extend(_render_note_pdf(target, fixed_text))
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
                    "后续需要登录态的工具（如 zju_get_video_url，投影抓取开启时还有 "
                    "zju_fetch_slides）会自动使用。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    if name == "zju_build_study_notes":
        return _build_study_notes(arguments)

    raise ValueError(f"Unknown tool: {name}")


def handle_tool_call(name: str, arguments: Dict[str, Any]) -> Any:
    """Execute a tool and redact secrets from whatever it returns.

    Before dispatch, every key must be declared in the tool's inputSchema.
    dsh 0.2.x does not close the root object, so an undeclared ``cookie`` /
    ``token`` field reaches the Python side and would already have been written
    to the host's call log. Refusing the call keeps the failure local.
    """
    tool = next((item for item in TOOLS if item["name"] == name), None)
    if tool is not None and isinstance(arguments, dict):
        allowed = set((tool["inputSchema"].get("properties") or {}).keys())
        unknown = sorted(key for key in arguments if key not in allowed)
        if unknown:
            raise ValueError("未知参数: " + ", ".join(unknown))
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
                "instructions": server_instructions(),
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": available_tools()}}

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}
        try:
            payload = handle_tool_call(tool_name, tool_args)
        except (
            ZJUAPIError,
            CoursewareError,
            CookieAccessError,
            SlidesDisabledError,
            StudyNotesDisabledError,
            LoginToolsDisabledError,
            ValueError,
        ) as exc:
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
        print("Tools loaded:", [t["name"] for t in available_tools()])
        print("Ready for MCP stdio connection.")
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--list-tools":
        print(json.dumps(available_tools(), ensure_ascii=False, indent=2))
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
