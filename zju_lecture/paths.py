# -*- coding: utf-8 -*-
"""Resolve model-supplied local paths against the *session* workspace.

Why this module exists
----------------------

The MCP / dsh server is a child process. Its own working directory is whatever
the host happened to spawn it with — the plugin spawns ``mcp_server.py`` from
the plugin root, a plain MCP host from wherever it likes. That directory is
**not** the directory the agent is working in.

A note that obviously exists (``知识总结.md`` in the workspace root) therefore
used to fail with ``错误: 找不到讲义文件`` because the lookup only consulted
``os.getcwd()``. The agent had to fall back to absolute paths, and the error
never said *where* the server looked, so the failure was hard to diagnose.

Resolution order (first hit wins, duplicates removed):

1. the path exactly as given — absolute paths always mean exactly one place;
2. ``ZJU_WORKSPACE`` — the session workspace, injected by the dsh plugin
   (see ``lib/bridge.js``) and settable by any host that knows better;
3. ``PWD`` — the directory the parent shell reported (POSIX convention);
4. the server's own working directory.

Every resolver also returns the list of candidates it tried, so the caller can
say ``找不到讲义文件: 知识总结.md（已尝试: ...）`` instead of a bare "not found".

Note on privacy: this module only *resolves* paths. The credential / browser
data guard still runs in :func:`zju_lecture.security.guard_local_file` before a
file is opened or created, and note writing refuses to leave the workspace.
"""

import os
import re
from typing import List, Optional, Sequence, Tuple

from .security import LocalFileError

#: The session workspace, injected by the host (dsh plugin sets it per call).
WORKSPACE_ENV = "ZJU_WORKSPACE"

#: Fallback used by hosts that only forward the shell's directory.
PWD_ENV = "PWD"

#: How many attempted paths are echoed back in an error message.
_MAX_REPORTED_CANDIDATES = 3

#: Characters that cannot appear in a file name on Windows (plus controls).
_UNSAFE_FILENAME_RE = re.compile(r'[\x00-\x1f\\/:*?"<>|\s]+')

#: Hard cap on the human-readable slug taken from a course title.
_SLUG_LIMIT = 24

#: Hard cap on an agent-authored note file name (whole stem, no extension).
_NAME_LIMIT = 80


def _normalize_directory(value: Optional[str]) -> Optional[str]:
    """Return ``value`` as an existing absolute directory, else ``None``."""
    if not value or not str(value).strip():
        return None
    try:
        expanded = os.path.abspath(os.path.expanduser(str(value).strip()))
    except (OSError, ValueError):
        return None
    return expanded if os.path.isdir(expanded) else None


def _current_directory() -> Optional[str]:
    """``os.getcwd()`` that survives a deleted working directory."""
    try:
        return _normalize_directory(os.getcwd())
    except (OSError, ValueError):
        return None


def workspace_roots() -> List[str]:
    """Directories a relative path may be resolved against, in priority order."""
    roots: List[str] = []
    seen = set()
    for value in (
        os.environ.get(WORKSPACE_ENV),
        os.environ.get(PWD_ENV),
        _current_directory(),
    ):
        normalized = _normalize_directory(value)
        if not normalized:
            continue
        key = os.path.normcase(normalized)
        if key in seen:
            continue
        seen.add(key)
        roots.append(normalized)
    return roots


def primary_workspace() -> str:
    """The directory a *new* file should be written to."""
    roots = workspace_roots()
    if roots:
        return roots[0]
    return _current_directory() or "."


def candidate_paths(raw: str) -> List[str]:
    """Every absolute path ``raw`` could refer to, in priority order."""
    text = str(raw or "").strip()
    if not text:
        return []

    expanded = os.path.expanduser(text)
    candidates: List[str] = []
    seen = set()

    def add(path: str) -> None:
        absolute = os.path.abspath(path)
        key = os.path.normcase(absolute)
        if key in seen:
            return
        seen.add(key)
        candidates.append(absolute)

    if os.path.isabs(expanded):
        add(expanded)
        return candidates

    for root in workspace_roots():
        add(os.path.join(root, expanded))
    return candidates


def describe_attempts(candidates: Sequence[str], limit: int = _MAX_REPORTED_CANDIDATES) -> str:
    """Render the tried paths for an error message (bounded, never empty)."""
    if not candidates:
        return ""
    shown = list(candidates[:limit])
    suffix = ""
    if len(candidates) > len(shown):
        suffix = f" 等 {len(candidates)} 处"
    return "（已尝试: " + ", ".join(shown) + suffix + "）"


def resolve_path(raw: str) -> Tuple[Optional[str], List[str]]:
    """Resolve ``raw`` to the first existing candidate.

    Returns ``(resolved_absolute_path, tried_candidates)``. ``resolved`` is
    ``None`` when nothing existed; ``tried`` is what the error message shows.
    """
    candidates = candidate_paths(raw)
    for candidate in candidates:
        try:
            if os.path.exists(candidate):
                return candidate, candidates
        except (OSError, ValueError):
            continue
    return None, candidates


def sanitize_slug(text: str, limit: int = _SLUG_LIMIT) -> str:
    """Turn a course title into a short, cross-platform file-name fragment."""
    compact = _UNSAFE_FILENAME_RE.sub("-", str(text or "").strip())
    compact = compact.strip("-._")
    compact = re.sub(r"-{2,}", "-", compact)
    return compact[:limit].strip("-._")


def sanitize_note_name(text: str, limit: int = _NAME_LIMIT) -> str:
    """Turn an agent-authored note title into a safe file stem.

    The agent names a note from the lecture's date and topic
    (``知识总结-2026-10-28-复变函数-保角映射``) because the note belongs to one
    lecture, not to "the plugin". A single shared ``知识总结.md`` is how one
    lecture's notes used to eat the previous lecture's notes.

    Only the stem is returned: separators are normalised, an ``.md`` suffix is
    dropped, and every character a file system may reject is folded to ``-``.
    An input that sanitises to nothing falls back to the caller's default.
    """
    value = str(text or "").strip()
    if value.lower().endswith(".md"):
        value = value[:-3]
    compact = _UNSAFE_FILENAME_RE.sub("-", value)
    compact = compact.strip("-._")
    compact = re.sub(r"-{2,}", "-", compact)
    return compact[:limit].strip("-._")


def note_filename(sub_id: str, slug: str = "") -> str:
    """Fallback lecture-note file name.

    Used only when the agent did not supply a name. It carries the ``sub_id``,
    so two different lectures can never silently overwrite each other — which
    is exactly what a bare ``知识总结.md`` allowed (and, being git-ignored,
    made unrecoverable).
    """
    identifier = sanitize_slug(str(sub_id or ""), limit=24) or "unknown"
    parts = ["知识总结", identifier]
    clean_slug = sanitize_slug(slug)
    if clean_slug:
        parts.append(clean_slug)
    return "-".join(parts) + ".md"


def _is_inside(directory: str, candidate: str) -> bool:
    try:
        parent = os.path.normcase(os.path.realpath(directory))
        child = os.path.normcase(os.path.realpath(candidate))
    except OSError:
        return False
    if parent == child:
        return True
    return child.startswith(parent.rstrip("\\/") + os.sep)


def note_target(
    sub_id: str,
    slug: str = "",
    directory: Optional[str] = None,
    name: str = "",
) -> Tuple[Optional[str], Optional[str]]:
    """Build the absolute path for a new note, staying inside a workspace root.

    Returns ``(path, error)``. ``name`` is the agent-chosen file stem
    (date + topic); when it is empty or sanitises to nothing, the ``sub_id``
    based fallback from :func:`note_filename` is used. ``directory`` (a
    sub-directory such as ``notes/2026``) must still resolve inside one of
    :func:`workspace_roots`; nothing outside the workspace is writable.
    """
    roots = workspace_roots()
    if not roots:
        return None, "无法确定当前工作目录，请改用绝对路径或设置 ZJU_WORKSPACE 环境变量"

    base = roots[0]
    if directory and str(directory).strip():
        extra = str(directory).strip()
        if os.path.isabs(extra):
            target_dir, tried = resolve_path(extra)
            if target_dir is None:
                return None, f"目标目录不存在: {extra}{describe_attempts(tried)}"
        else:
            target_dir = os.path.join(base, extra)
        if not _is_inside(base, target_dir):
            return None, f"拒绝写入工作区之外的目录: {extra}"
    else:
        target_dir = base

    custom = sanitize_note_name(name)
    filename = f"{custom}.md" if custom else note_filename(sub_id, slug)
    target = os.path.join(target_dir, filename)
    if not _is_inside(base, target):
        return None, f"拒绝写入工作区之外的位置: {target}"
    return target, None


def artifact_dir(
    subdir: str = "",
    default: str = "artifacts",
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve and create a directory for generated artifacts.

    Used for downloaded slide screenshots and PDFs. ``subdir`` is relative to
    the primary workspace, or an absolute path already inside it; empty input
    falls back to ``default``. Returns ``(absolute_dir, error)``. Nothing
    outside the workspace is writable, so a model-chosen ``output_dir`` cannot
    be turned into an arbitrary file-system write.
    """
    roots = workspace_roots()
    if not roots:
        return None, "无法确定当前工作目录，请改用绝对路径或设置 ZJU_WORKSPACE 环境变量"
    base = roots[0]
    raw = str(subdir or "").strip() or str(default or "").strip() or "artifacts"
    candidate = (
        os.path.abspath(os.path.expanduser(raw))
        if os.path.isabs(raw)
        else os.path.join(base, raw)
    )
    if not _is_inside(base, candidate):
        return None, f"拒绝写入工作区之外的目录: {raw}"
    try:
        os.makedirs(candidate, exist_ok=True)
    except OSError as exc:
        return None, f"无法创建输出目录 {candidate}: {exc}"
    if not _is_inside(base, candidate):
        return None, f"拒绝写入工作区之外的目录: {raw}"
    return candidate, None
