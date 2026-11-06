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
from .study_notes import (
    CompileResult,
    DraftResult,
    RenderResult,
    StudyNotesError,
    build_draft,
    compile_project,
    find_typst,
    render_typst,
)

# The projection pipeline is an optional feature: importing this package (for
# example just to fetch a transcript) must not load the screenshot/PDF module.
# The public names stay importable through PEP 562 lazy attributes, so
# ``from zju_lecture import download_slides`` still works and only then pulls
# in ``zju_lecture.slides``.
_LAZY_EXPORTS = {
    "SlideError": ".slides",
    "build_slides_pdf": ".slides",
    "download_slides": ".slides",
    # The reading-PDF pipeline is only needed after a note is written; a
    # transcript-only process should never pay for loading it.
    "HandoutResult": ".handout",
    "HandoutCompileResult": ".handout",
    "render_handout": ".handout",
    "compile_handout": ".handout",
    "compile_handout_file": ".handout",
    # The login window is interactive: import it only when the user actually
    # opens it, not for every transcript fetch.
    "LoginError": ".browser_login",
    "open_login_window": ".browser_login",
    "load_session_cookie": ".browser_login",
    "save_session": ".browser_login",
    "clear_session": ".browser_login",
    "session_summary": ".browser_login",
    "login_available": ".browser_login",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value

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
    "HandoutResult",
    "HandoutCompileResult",
    "render_handout",
    "compile_handout",
    "compile_handout_file",
    "LoginError",
    "open_login_window",
    "load_session_cookie",
    "save_session",
    "clear_session",
    "session_summary",
    "login_available",
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
    "StudyNotesError",
    "DraftResult",
    "RenderResult",
    "CompileResult",
    "build_draft",
    "render_typst",
    "compile_project",
    "find_typst",
]
