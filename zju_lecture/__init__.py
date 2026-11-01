# -*- coding: utf-8 -*-
"""
ZJU Lecture Agent Core Package
Tools and API client for fetching transcripts, slides, and courseware.

Shared by the DeepSeek Harness (dsh) plugin and the standard MCP server: both
ship this same implementation, so their tools behave identically.
"""

from .client import (
    BASE_URL,
    ZJUAPIError,
    extract_classroom_token,
    fetch_slides,
    fetch_transcript,
    fetch_video_url,
    is_zju_host,
    normalize_slide,
    parse_lecture_url,
    secure_zju_url,
)
from .cookies import CookieAccessError, get_edge_cookie, read_edge_cookies
from .courseware import CoursewareError, extract_courseware_text
from .note_lint import Issue, check_markdown, fix_markdown, format_report, write_atomic
from .paths import (
    artifact_dir,
    describe_attempts,
    note_filename,
    note_target,
    resolve_path,
)
from .slides import SlideError, build_slides_pdf, download_slides
from .formatter import (
    build_transcript_views,
    chunk_transcript,
    filter_segments,
    format_minute_span,
    format_quality_line,
    format_slides_as_markdown,
    format_timestamp,
    transcript_quality,
)
from .security import (
    REDACTOR,
    LocalFileError,
    SecretRedactor,
    describe_cookie,
    guard_local_file,
    mask_cookie_header,
    sanitize_cookie_header,
)

__all__ = [
    "BASE_URL",
    "ZJUAPIError",
    "CookieAccessError",
    "CoursewareError",
    "SlideError",
    "parse_lecture_url",
    "fetch_transcript",
    "fetch_slides",
    "fetch_video_url",
    "normalize_slide",
    "extract_classroom_token",
    "is_zju_host",
    "secure_zju_url",
    "download_slides",
    "build_slides_pdf",
    "extract_courseware_text",
    "check_markdown",
    "fix_markdown",
    "format_report",
    "write_atomic",
    "Issue",
    "get_edge_cookie",
    "read_edge_cookies",
    "describe_attempts",
    "artifact_dir",
    "note_filename",
    "note_target",
    "resolve_path",
    "format_timestamp",
    "format_minute_span",
    "filter_segments",
    "build_transcript_views",
    "chunk_transcript",
    "format_slides_as_markdown",
    "format_quality_line",
    "transcript_quality",
    "REDACTOR",
    "LocalFileError",
    "SecretRedactor",
    "describe_cookie",
    "guard_local_file",
    "mask_cookie_header",
    "sanitize_cookie_header",
]
