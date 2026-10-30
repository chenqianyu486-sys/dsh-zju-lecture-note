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
    fetch_slides,
    fetch_transcript,
    fetch_video_url,
    parse_lecture_url,
)
from .cookies import CookieAccessError, get_edge_cookie, read_edge_cookies
from .courseware import CoursewareError, extract_courseware_text
from .note_lint import Issue, check_markdown, fix_markdown, format_report
from .formatter import (
    build_transcript_views,
    chunk_transcript,
    filter_segments,
    format_minute_span,
    format_slides_as_markdown,
    format_timestamp,
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
    "parse_lecture_url",
    "fetch_transcript",
    "fetch_slides",
    "fetch_video_url",
    "extract_courseware_text",
    "check_markdown",
    "fix_markdown",
    "format_report",
    "Issue",
    "get_edge_cookie",
    "read_edge_cookies",
    "format_timestamp",
    "format_minute_span",
    "filter_segments",
    "build_transcript_views",
    "chunk_transcript",
    "format_slides_as_markdown",
    "REDACTOR",
    "LocalFileError",
    "SecretRedactor",
    "describe_cookie",
    "guard_local_file",
    "mask_cookie_header",
    "sanitize_cookie_header",
]
