# -*- coding: utf-8 -*-
"""
Lecture-note Markdown render lint.

Static checks only — no rendering, no network, zero dependencies.
The rules mirror the "公式书写规范" section of the skill instructions, so a
generated note can be validated mechanically instead of trusted blindly.

Two severity levels:

* ``error`` — the note will visibly break in a Markdown renderer
  (a table column cut in half, an unrendered formula, a collapsed block).
* ``warn``  — the note renders, but breaks the agreed notation convention.
"""

import os
import re
import shutil
import tempfile
import time
from typing import List, NamedTuple

ERROR = "error"
WARN = "warn"

# Inline math: ``$...$`` but not ``$$...$$``.
_INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)

# A literal pipe inside math. Only ``\|`` is a legal escape; ``\lvert`` and
# friends contain no pipe character at all, so any bare ``|`` is a real one.
_BARE_PIPE_RE = re.compile(r"(?<!\\)\|")

# ``\frac12`` / ``\frac{1}2`` — braces are mandatory on both sides.
_FRAC_NO_BRACE_RE = re.compile(r"\\frac\s*(?!\{)")
_FRAC_DENOM_NO_BRACE_RE = re.compile(r"\\frac\s*\{[^{}]*\}\s*(?!\{)")

_DFRAC_RE = re.compile(r"\\dfrac\b")

# ``\text{...}`` holding CJK — different renderers fall back differently.
_TEXT_CMD_RE = re.compile(r"\\text\{([^}]*)\}")
_CJK_RE = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")

# A bare imaginary unit. ``x_i`` and ``\mathrm{i}`` are fine; ``i`` is not.
_BARE_IMAG_RE = re.compile(r"(?<![A-Za-z0-9_{])i(?![A-Za-z0-9_])")
_IMAG_CMD_RE = re.compile(r"\\mathrm\{[ij]\}")

_INLINE_CODE_RE = re.compile(r"`[^`]*`")


class Issue(NamedTuple):
    """One lint finding."""

    line: int
    level: str
    code: str
    message: str
    hint: str
    excerpt: str


def _excerpt(line: str, limit: int = 120) -> str:
    line = line.strip()
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _iter_inline_math(line: str):
    """Yield ``(start_offset, math_body)`` for each inline formula."""
    for match in _INLINE_MATH_RE.finditer(line):
        yield match.start(1), match.group(1)


def check_markdown(text: str) -> List[Issue]:
    """Check a lecture-note Markdown document and return the findings."""
    issues: List[Issue] = []
    lines = text.split("\n")

    in_fence = False
    in_display = False
    display_start = 0

    for idx, raw in enumerate(lines, start=1):
        stripped = raw.strip()

        # Fenced code blocks: never lint their contents.
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        # Block display math: ``$$`` alone on its own line.
        if stripped == "$$":
            if not in_display:
                in_display = True
                display_start = idx
                if idx > 1 and lines[idx - 2].strip() != "":
                    issues.append(Issue(
                        idx, ERROR, "display_not_isolated",
                        "块级公式 `$$` 之前必须留一个空行",
                        "部分渲染器要求 `$$` 块前后各有一个空行，否则整块不渲染。",
                        _excerpt(lines[idx - 2]),
                    ))
            else:
                in_display = False
                if idx < len(lines) and lines[idx].strip() != "":
                    issues.append(Issue(
                        idx, ERROR, "display_not_isolated",
                        "块级公式 `$$` 之后必须留一个空行",
                        "部分渲染器要求 `$$` 块前后各有一个空行，否则整块不渲染。",
                        _excerpt(lines[idx]),
                    ))
            continue

        if in_display:
            continue

        # Inline code spans are not math.
        probe = _INLINE_CODE_RE.sub(" ", raw)

        if "$$" in probe:
            issues.append(Issue(
                idx, ERROR, "display_inline",
                "块级公式必须独占一行，不能写成 `$$...$$`",
                "把 `$$` 放到独立的两行上，中间是公式内容。",
                _excerpt(stripped),
            ))
            # Keep the inner formula in scope so its own problems (a missing
            # brace, a bare pipe) are reported in the same pass.
            probe = re.sub(r"\$\$(.+?)\$\$", r"$\1$", probe)

        is_table_row = probe.lstrip().startswith("|")

        # Per-formula checks.
        for offset, body in _iter_inline_math(probe):
            line_no = idx
            body_stripped = body.strip()

            if is_table_row and _BARE_PIPE_RE.search(body):
                issues.append(Issue(
                    line_no, ERROR, "table_bare_pipe",
                    "表格单元格内的公式出现裸竖线 `|`，会把该列截断",
                    "绝对值/模一律写 `\\lvert ... \\rvert`。",
                    _excerpt(stripped),
                ))

            if _FRAC_NO_BRACE_RE.search(body_stripped):
                issues.append(Issue(
                    line_no, ERROR, "frac_no_brace",
                    "分式的分子未用花括号",
                    "写成 `\\frac{分子}{分母}`，不要写 `\\frac12`。",
                    _excerpt(stripped),
                ))
            elif _FRAC_DENOM_NO_BRACE_RE.search(body_stripped):
                issues.append(Issue(
                    line_no, ERROR, "frac_no_brace",
                    "分式的分母未用花括号",
                    "写成 `\\frac{分子}{分母}`，不要写 `\\frac{1}2`。",
                    _excerpt(stripped),
                ))

            if _DFRAC_RE.search(body_stripped):
                issues.append(Issue(
                    line_no, WARN, "dfrac_used",
                    "使用了 `\\dfrac`",
                    "行内与独立公式统一用 `\\frac`；行内 `\\dfrac` 会被放大、行距失控。",
                    _excerpt(stripped),
                ))

            for text_match in _TEXT_CMD_RE.finditer(body_stripped):
                if _CJK_RE.search(text_match.group(1)):
                    issues.append(Issue(
                        line_no, WARN, "text_cjk",
                        "`\\text{}` 里放了中文",
                        "中文说明写到公式外面，避免不同渲染器的字体回退差异。",
                        _excerpt(stripped),
                    ))
                    break

            imag_probe = _IMAG_CMD_RE.sub(" ", body_stripped)
            if _BARE_IMAG_RE.search(imag_probe):
                issues.append(Issue(
                    line_no, WARN, "bare_imaginary_unit",
                    "虚数单位写成了裸 `i`",
                    "统一写 `\\mathrm{i}`，避免与变量名混淆。",
                    _excerpt(stripped),
                ))

        # Unbalanced inline math on this line.
        if probe.count("$") % 2 == 1:
            issues.append(Issue(
                idx, ERROR, "inline_math_unclosed",
                "行内公式的 `$` 没有成对闭合",
                "检查这一行的 `$` 数量是否为偶数。",
                _excerpt(stripped),
            ))

        # Collapsible blocks must span multiple lines. Tags mentioned inside
        # inline code spans are documentation, not real markup.
        if "<details>" in probe and "</details>" in probe:
            issues.append(Issue(
                idx, ERROR, "details_single_line",
                "`<details>` 与 `</details>` 写在同一行",
                "折叠块必须写成多行形式，否则块内的 Markdown 与公式都不会渲染。",
                _excerpt(stripped),
            ))
        elif "</summary>" in probe and probe.split("</summary>", 1)[1].strip():
            issues.append(Issue(
                idx, ERROR, "summary_inline_content",
                "`<summary>` 后面同一行还有正文",
                "`<summary>` 与正文之间留一个空行，正文才会作为 Markdown 解析。",
                _excerpt(stripped),
            ))

    if in_display:
        issues.append(Issue(
            display_start, ERROR, "display_unclosed",
            "块级公式 `$$` 没有闭合",
            "补上结束用的 `$$` 独占行。",
            "",
        ))

    return issues


def _group_by_code(issues: List[Issue]) -> List[List[Issue]]:
    """Group findings by ``code``, errors first, each group in line order."""
    groups = {}
    for issue in issues:
        groups.setdefault(issue.code, []).append(issue)
    ordered = sorted(
        groups.values(),
        key=lambda group: (0 if group[0].level == ERROR else 1, group[0].line),
    )
    return ordered


def _format_line_numbers(lines: List[int], limit: int) -> str:
    """``L108, L112, L119（共 59 处，其余 56 处已省略）`` — bounded line list."""
    if limit <= 0:
        return f"共 {len(lines)} 处"
    shown = lines[:limit]
    text = ", ".join(f"L{line}" for line in shown)
    if len(lines) > len(shown):
        text += f"（共 {len(lines)} 处，其余 {len(lines) - len(shown)} 处已省略）"
    else:
        text += f"（共 {len(lines)} 处）"
    return text


def format_report(path: str, issues: List[Issue], max_samples: int = 3) -> str:
    """Render the findings as the text the agent reads back.

    Findings are grouped by ``code``: a long note with 59 un-isolated ``$$``
    blocks used to repeat the same 问题 / 修法 / 原文 triple 59 times, which
    burned a large slice of the agent's context on pure noise. One block per
    code, with a bounded list of line numbers, carries the same information —
    and ``fix=true`` can still repair every one of them.

    ``max_samples`` bounds how many line numbers are listed per group
    (``0`` = count only). :func:`check_markdown` still returns the full list,
    so programmatic callers lose nothing.
    """
    errors = [i for i in issues if i.level == ERROR]
    warns = [i for i in issues if i.level == WARN]
    groups = _group_by_code(issues)

    header = f"错误 {len(errors)} | 警告 {len(warns)}"
    if issues:
        header += f" | 涉及 {len(groups)} 类问题"

    lines = [
        f"=== 讲义渲染规范检查 ({path}) ===",
        header,
        "",
    ]

    if not issues:
        lines.append("结论: 通过 —— 未发现问题。")
        return "\n".join(lines)

    for group in groups:
        first = group[0]
        tag = "错误" if first.level == ERROR else "警告"
        count = f" × {len(group)}" if len(group) > 1 else ""
        lines.append(f"[{tag}] {first.code}{count}")
        lines.append(f"  问题: {first.message}")
        lines.append(f"  修法: {first.hint}")
        lines.append(f"  位置: {_format_line_numbers([i.line for i in group], max_samples)}")
        samples = [i for i in group if i.excerpt][:max_samples]
        for sample in samples:
            lines.append(f"  示例: L{sample.line} · {sample.excerpt}")
        lines.append("")

    if errors:
        lines.append("结论: 不通过 —— 存在会破坏渲染的错误，请修正后重新检查。")
        lines.append(
            "提示: 若多项错误属于可机械修复的类型，可直接用 fix=true 回写后重新检查。"
        )
    else:
        lines.append("结论: 通过渲染检查（仅有规范性警告）。")
    return "\n".join(lines)


# --------------------------------------------------------------------- autofix

_FRAC_PLAIN_RE = re.compile(r"\\frac\s*([A-Za-z0-9])\s*([A-Za-z0-9])")
_FRAC_NUM_ONLY_RE = re.compile(r"\\frac\s*([A-Za-z0-9])\s*(\{[^{}]*\})")
_FRAC_DEN_ONLY_RE = re.compile(r"\\frac\s*(\{[^{}]*\})\s*([A-Za-z0-9])")
_PAIRED_PIPE_RE = re.compile(r"\|([^|\\\n]+)\|")
_SINGLE_LINE_DETAILS_RE = re.compile(
    r"^(\s*)<details>\s*<summary>(.*?)</summary>(.*?)</details>\s*$"
)


def _fix_fracs(text: str) -> tuple:
    text, n1 = _FRAC_PLAIN_RE.subn(r"\\frac{\1}{\2}", text)
    text, n2 = _FRAC_NUM_ONLY_RE.subn(r"\\frac{\1}{\2}", text)
    text, n3 = _FRAC_DEN_ONLY_RE.subn(r"\\frac{\1}{\2}", text)
    return text, n1 + n2 + n3


def _fix_table_pipes_segment(line: str) -> tuple:
    """Turn ``|x|`` into ``\\lvert x\\rvert`` inside table-cell formulas."""
    changed = False

    def replace(match):
        nonlocal changed
        body = match.group(1)
        new_body, count = _PAIRED_PIPE_RE.subn(
            # The space after \lvert is mandatory: "\lverty" would be read as a
            # single undefined control sequence.
            lambda m: "\\lvert " + m.group(1).strip() + "\\rvert", body
        )
        if count:
            changed = True
        return "$" + new_body + "$"

    new_line = _INLINE_MATH_RE.sub(replace, line)
    return new_line, 1 if changed else 0


def _fix_table_pipes(line: str) -> tuple:
    """Fix table-cell pipes, skipping inline-code spans."""
    return _apply_outside_code(line, _fix_table_pipes_segment)


def _normalize_math(text: str) -> tuple:
    """``\\dfrac`` -> ``\\frac`` and ``\\frac12`` -> ``\\frac{1}{2}``."""
    count = 0
    if "\\dfrac" in text:
        count += text.count("\\dfrac")
        text = text.replace("\\dfrac", "\\frac")
    text, frac_count = _fix_fracs(text)
    return text, count + frac_count


def _apply_outside_code(line: str, func) -> tuple:
    """Apply ``func`` to the parts of *line* outside inline-code spans.

    Backtick code spans are documentation about the rules, not formulas that
    obey them: a note saying ``frac12`` is wrong must keep saying so after an
    autofix. Returns ``(new_line, number_of_changes)``.
    """
    out = []
    changes = 0
    pos = 0
    in_code = False
    open_at = 0
    for idx, ch in enumerate(line):
        if ch != "`":
            continue
        if not in_code:
            piece, count = func(line[pos:idx])
            out.append(piece)
            changes += count
            in_code = True
            open_at = idx
            pos = idx
        else:
            out.append(line[open_at:idx + 1])
            pos = idx + 1
            in_code = False
    if in_code:
        # Unclosed backtick: the rest is code, never rewrite it.
        out.append(line[pos:])
    else:
        piece, count = func(line[pos:])
        out.append(piece)
        changes += count
    return "".join(out), changes


#: Host-configurable backup directory. Empty = the default below.
BACKUP_DIR_ENV = "ZJU_BACKUP_DIR"

#: Default backup root, under the system temp directory.
_BACKUP_DIRNAME = "zju-lecture-backups"


def backup_directory() -> str:
    """Directory that receives pre-autofix backups.

    Backups used to land next to the note as ``<note>.md.bak``. Lectures live
    in the workspace root, so every ``fix=true`` added an untracked file to
    ``git status`` — noise the user never asked for. The default is now the
    system temp directory (returned as an absolute path in the report), and
    ``ZJU_BACKUP_DIR`` lets a host point it at a directory of its own.
    """
    override = os.environ.get(BACKUP_DIR_ENV, "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(tempfile.gettempdir(), _BACKUP_DIRNAME)


def _unique_backup_path(directory: str, source: str) -> str:
    stem = os.path.splitext(os.path.basename(source))[0] or "note"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = os.path.join(directory, f"{stem}.{stamp}.bak")
    counter = 1
    while os.path.exists(candidate):
        counter += 1
        candidate = os.path.join(directory, f"{stem}.{stamp}-{counter}.bak")
    return candidate


def write_atomic(path: str, text: str) -> None:
    """Atomically replace ``path`` with ``text`` (UTF-8, LF newlines).

    The bytes go to a temporary file in the same directory and are renamed
    over the target, so a crash mid-write can never leave a half-written note.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".zju-note-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_with_backup(path: str, text: str, backup_dir: str = None) -> str:
    """Back ``path`` up, then atomically replace it. Returns the backup path.

    The backup is written before the replace, so a failed write never leaves
    the user without their original note. Raises ``OSError`` on failure; at
    that point the original file is still intact.

    ``backup_dir`` (or ``ZJU_BACKUP_DIR``) selects the destination; when it
    cannot be created the backup falls back to ``<path>.bak`` so the data is
    never silently unprotected.
    """
    directory = os.path.abspath(os.path.expanduser(backup_dir)) if backup_dir else backup_directory()
    try:
        os.makedirs(directory, exist_ok=True)
        backup = _unique_backup_path(directory, path)
    except OSError:
        backup = path + ".bak"
    shutil.copyfile(path, backup)
    write_atomic(path, text)
    return backup


def _isolate_display_blocks(lines: List[str]) -> tuple:
    """Give every multi-line ``$$`` block a blank line before and after it.

    ``check_markdown`` flags a ``$$`` block glued to prose, but the autofix
    could not repair it — a long note that missed the blank lines produced
    dozens of errors that were reported and never fixed. The rewrite is purely
    mechanical: insert one blank line, change no formula.

    Three details make it safe:

    * the open and the close marker are told apart by ``inside``: putting a
      blank line around *every* ``$$`` line would punch holes into the formula
      body;
    * fenced code blocks are skipped, so a document that *demonstrates* the
      rule keeps its example intact;
    * the indentation of the ``$$`` lines is left exactly as written, so a
      display block inside a list item stays inside that list.

    Returns ``(new_lines, number_of_inserted_blank_lines)``.
    """
    out: List[str] = []
    in_fence = False
    inside = False
    pending_blank = False
    fixed = 0

    def settle() -> None:
        nonlocal pending_blank
        if pending_blank:
            out.append("")
            pending_blank = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if pending_blank:
                pending_blank = False
                out.append("")
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        if stripped == "$$":
            if not inside:
                if out and out[-1].strip() != "":
                    out.append("")
                    fixed += 1
                out.append(line)
                inside = True
            else:
                out.append(line)
                inside = False
                pending_blank = True
            continue

        if stripped == "":
            pending_blank = False
            out.append(line)
            continue

        settle()
        out.append(line)

    return out, fixed


def fix_markdown(text: str) -> tuple:
    """Apply the mechanical fixes and return ``(new_text, applied_notes)``.

    Only unambiguous, semantics-preserving rewrites are applied. Anything that
    needs a human decision (an unpaired pipe, a bare imaginary unit, a ``\\text{}``
    block holding Chinese) is left alone and stays reported by ``check_markdown``.
    """
    applied = []
    lines = text.split("\n")

    out = []
    in_fence = False
    display_fixed = 0
    math_fixed = 0
    pipe_fixed = 0
    details_fixed = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        # Single-line ``<details>`` block -> multi-line form.
        details_match = _SINGLE_LINE_DETAILS_RE.match(line)
        if details_match:
            indent = details_match.group(1)
            summary = details_match.group(2).strip()
            content = details_match.group(3).strip()
            out.append(f"{indent}<details>")
            out.append(f"{indent}<summary>{summary}</summary>")
            out.append("")
            out.append(f"{indent}{content}" if content else "")
            out.append("")
            out.append(f"{indent}</details>")
            details_fixed += 1
            continue

        # Single-line ``$$ ... $$`` -> an isolated three-line block.
        display_match = re.match(r"^(\s*)\$\$(.+)\$\$\s*$", line)
        if display_match and "`" not in line:
            indent = display_match.group(1)
            body, count = _normalize_math(display_match.group(2).strip())
            math_fixed += count
            out.append(indent + "$$")
            out.append(body)
            out.append(indent + "$$")
            display_fixed += 1
            continue

        # ``\dfrac`` -> ``\frac``; ``\frac12`` -> ``\frac{1}{2}``.
        # Inline-code spans are left alone: they document the rule, they do not
        # violate it.
        line, count = _apply_outside_code(line, _normalize_math)
        math_fixed += count

        # Bare pipes inside table-cell formulas.
        if line.lstrip().startswith("|"):
            line, changed = _fix_table_pipes(line)
            if changed:
                pipe_fixed += 1

        out.append(line)

    out, isolated_fixed = _isolate_display_blocks(out)
    new_text = "\n".join(out)

    if display_fixed:
        applied.append(f"拆分 {display_fixed} 处单行 $$ 公式块为独占三行")
    if isolated_fixed:
        applied.append(f"为 {isolated_fixed} 处块级公式补全前后空行")
    if math_fixed:
        applied.append(f"统一 {math_fixed} 处分式写法（\\dfrac -> \\frac、\\frac 补花括号）")
    if pipe_fixed:
        applied.append(f"将 {pipe_fixed} 处表格公式内的裸竖线改为 \\lvert ... \\rvert")
    if details_fixed:
        applied.append(f"将 {details_fixed} 处单行 <details> 折叠块改为多行形式")

    return new_text, applied

