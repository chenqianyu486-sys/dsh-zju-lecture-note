# -*- coding: utf-8 -*-
"""讲义 Markdown → 可阅读的 Typst/PDF（自动排版，不是填空笔记）。

为什么单独一条链路
------------------
``study_notes.py`` 做的是「填空式学习笔记」：底稿里要人工判断哪句是定理、
哪里挖空，再由 scholia 模板排版。那份 PDF 的读者是**要动笔复习的人**。

本模块做的是另一件事：``zju_write_note`` 写下的普通讲义，直接排成一份
**能连续读下去的 PDF**。它不要求作者补任何标记、不挖空、不插练习块；
标题、段落、列表、表格、公式、代码、引用、图片都按 Markdown 原样搬运。
没有这一步时，用户拿到的是 Markdown；有这一步时，同一份内容多一个
「排版好、可打印、可分享」的 PDF，而 Agent 一次工具调用都不用多发。

Token 账
--------
PDF 由 Python 在本地生成，Agent 只收到一行路径与页数，不需要把讲义内容
再回显一遍。排版失败也不影响 Markdown 写入：这条链路是**增益**，不是前置。

设计边界
--------
只支持讲义里常见的 Markdown 子集；遇到不认识的块级语法时尽量降级成段落，
并在 ``HandoutResult.warnings`` 里点名，而不是静默吞掉或编造。
数学仍走 ``study_notes.latex_to_typst`` 的同一套转换，保证两份 PDF 对公式的
理解一致。

只依赖标准库；Typst 是可选的外部可执行文件。
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .study_notes import (
    KNOT_BUDGET_PER_SECTION,
    MARKERS,
    StudyNotesError,
    _run_typst,
    _SUMMARY_LINE_RE,
    _UNKNOWN_MARKER_RE,
    block_boundary,
    find_typst,
    latex_to_typst,
    pad_inline_math,
    split_quote_items,
    split_question_number,
    split_review_labels,
    strip_heading_number,
)

__all__ = [
    "HandoutResult",
    "HandoutCompileResult",
    "render_handout",
    "compile_handout",
    "compile_handout_file",
]

#: 讲义 PDF 的 Typst 构建目录名（位于工作区，已 gitignore）。
BUILD_DIR_NAME = ".zju-lecture"

#: 讲义 PDF 的固定排版参数。与 study_notes 保持同一套中文阅读参数：
#: 段首空两格、段间距略大于行间距、块级公式与段间距解耦。
#: 具体样式在自包含的 ``handout_prelude.typ`` 里；这里保留常量是为了让
#: 测试和文档能引用同一组数值。
BODY_LEADING = "0.72em"
BODY_SPACING = "0.95em"
EQUATION_BLOCK_SPACING = "1.6em"

#: 行内特殊字符。Typst 的 markup 里这些字符会改变结构，纯文本必须转义。
_INLINE_ESCAPES = {
    "\\": "\\\\",
    "#": "\\#",
    "[": "\\[",
    "]": "\\]",
    "_": "\\_",
    "@": "\\@",
    "<": "\\<",
    ">": "\\>",
    "*": "\\*",
    "~": "\\~",
    "$": "\\$",
}

#: CJK 字符（用于判断折行处该不该补空格）。
_CJK_RE = re.compile(
    r"[\u2e80-\u9fff\u3000-\u303f\uff00-\uffef\uf900-\ufaff]"
)

#: Markdown 块级结构的开头。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^(```+|~~~+)\s*([^\s`]*)?.*$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEP_RE = re.compile(
    r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$"
)
_IMAGE_RE = re.compile(r'^!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+"[^"]*")?\s*\)$')
_HR_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
#: 只剩破折号的「正文」：`[例] 标题 ——` 拆出来的残渣。
_DASH_ONLY_RE = re.compile(r"^[—–-]+$")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_DETAILS_OPEN_RE = re.compile(r"<details[^>]*>", re.IGNORECASE)
_DETAILS_CLOSE_RE = re.compile(r"</details\s*>", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"<summary[^>]*>(.*?)</summary\s*>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


# --------------------------------------------------------------------- 结果类型


@dataclass
class HandoutResult:
    """一份讲义 → Typst 的结果。"""

    typst: str
    warnings: List[str] = field(default_factory=list)
    title: str = ""
    subtitle: str = ""
    date: str = ""
    sections: int = 0
    blocks: Dict[str, int] = field(default_factory=dict)


@dataclass
class HandoutCompileResult:
    """一份讲义 → PDF 的结果。"""

    ok: bool
    pdf_path: str = ""
    pages: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    output: str = ""


# ------------------------------------------------------------------- 小工具


def _json_string(value: str) -> str:
    """Typst 的字符串字面量（JSON 字符串与 Typst 的转义足够接近）。"""
    return json.dumps(str(value), ensure_ascii=False)


def _handout_prelude_text() -> str:
    """读取自包含的讲义模板。

    这份模板不 import 任何 Typst Universe 包：讲义 PDF 是默认链路，
    第一次编译就去包注册表拉依赖会把「本地排版」变成网络请求。模板随
    包分发，``pyproject.toml`` / ``package.json`` 的 package-data 负责带上它。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "handout_prelude.typ")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise StudyNotesError(f"缺少随包讲义模板: {path}（{exc}）") from exc


def _escape_inline(text: str) -> str:
    """把纯文本转成 Typst markup 里的字面量。"""
    out: List[str] = []
    for char in text:
        out.append(_INLINE_ESCAPES.get(char, char))
    return "".join(out)


def _is_cjk(char: str) -> bool:
    return bool(char and _CJK_RE.match(char))


#: Markdown 的硬换行（行尾两个空格）在拼接时留下的占位符。
#: 它不能直接变成 `#linebreak()` 字符串——那会被行内转义成字面量。
_HARD_BREAK = "\x00ZJU_HARD_BREAK\x00"


def _join_paragraph(lines: Sequence[str]) -> str:
    """把 Markdown 段落内的软换行拼回一行。

    中文行尾没有空格，直接补空格会在词中间多出空隙；英文句子则需要空格。
    这里按两侧字符是否为 CJK 决定：两侧都是 CJK（或中文标点）就不加空格。
    行尾两个空格是硬换行，用占位符保留给 :func:`_render_rich_text`。
    """
    parts: List[str] = []
    for raw in lines:
        line = raw.rstrip()
        if not line:
            continue
        if not parts:
            parts.append(raw.rstrip("\n"))
            continue
        previous = parts[-1]
        if previous.endswith("  ") and previous != _HARD_BREAK:
            parts[-1] = previous.rstrip()
            parts.append(_HARD_BREAK)
            parts.append(line.lstrip())
            continue
        if previous == _HARD_BREAK:
            parts.append(line.lstrip())
            continue
        if _is_cjk(previous[-1:]) and _is_cjk(line.lstrip()[:1]):
            parts.append(line.lstrip())
        else:
            parts.append(" " + line.lstrip())
    return "".join(parts)


def _render_rich_text(text: str, warnings: List[str], image_resolver) -> str:
    """渲染段落文本；硬换行在行内渲染之外拼成 Typst 的 ``#linebreak()``。"""
    if _HARD_BREAK not in text:
        return _render_inline(text, warnings, image_resolver)
    segments = text.split(_HARD_BREAK)
    return "#linebreak()".join(
        _render_inline(segment, warnings, image_resolver) for segment in segments
    )


def _split_table_row(row: str) -> List[str]:
    """按未转义的 ``|`` 切表格行，保留单元格里的 ``\\|``。"""
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells = re.split(r"(?<!\\)\|", body)
    return [cell.strip().replace("\\|", "|") for cell in cells]


def _resolve_image(
    source: str,
    note_dir: str,
    workspace_root: str,
) -> Tuple[Optional[str], str]:
    """把 Markdown 图片路径转成 Typst 以 ``/`` 开头的 root 相对路径。

    返回 ``(typst_path, warning)``。Typst 的 ``--root`` 会限制可读文件，
    所以只有工作区内的本地图片能进 PDF；外链不下载、不联网。
    """
    raw = str(source or "").strip()
    if not raw:
        return None, "图片缺少路径"
    if raw.startswith(("http://", "https://", "data:")):
        return None, f"外链图片不下载（{raw}）"
    if not workspace_root:
        workspace_root = note_dir
    root = os.path.abspath(workspace_root)
    candidate = raw
    if not os.path.isabs(candidate):
        candidate = os.path.join(note_dir, candidate)
    candidate = os.path.abspath(os.path.expanduser(candidate))
    try:
        inside = os.path.commonpath([root, candidate]) == root
    except ValueError:
        inside = False
    if not inside:
        return None, f"图片在工作区之外，未嵌入（{raw}）"
    if not os.path.isfile(candidate):
        return None, f"找不到图片（{raw}）"
    relative = os.path.relpath(candidate, root).replace(os.sep, "/")
    return "/" + relative, ""


# ------------------------------------------------------------------ 行内渲染

#: 底稿标记（与 ``study_notes.MARKERS`` 共用一张表：两条链路语义一致）。
_MARKER_BLOCK_RE = re.compile(r"^\[([^\]\n]{1,4})\]\s*(.*)$")
#: 行尾交叉引用标签（``<def:x>``）。
_LABEL_RE = re.compile(r"\s*<([A-Za-z][A-Za-z0-9_.:-]*)>\s*$")
#: 正文里的回指（``@def:x``）。
_REF_RE = re.compile(r"@[A-Za-z][A-Za-z0-9_.:-]*")
#: 行内缺口（``[缺口: …]``）。
_GAP_RE = re.compile(r"\[缺口\s*[:：]\s*([^\]]*)\]")
#: 会编号、也占「方框预算」的装置。
_KNOT_CALLS: Dict[str, Tuple[str, str]] = {
    "theorem": ("Theorem", "thm"),
    "lemma": ("Lemma", "thm"),
    "proposition": ("Proposition", "thm"),
    "corollary": ("Corollary", "thm"),
    "definition": ("Definition", "def"),
    "axiom": ("Axiom", "def"),
    "assumption": ("Assumption", "def"),
    "notation": ("Notation", "def"),
    "example": ("Example", "eg"),
}
#: 与 prelude.typ 的 soft-palette 逐角色一致；由 tools/sync_palette.py 生成，不要手改。
_PALETTE = {
    "bg": "#FDFDFB",
    "ink": "#1A1A1C",
    "muted": "#6F7683",
    "hairline": "#DBDFE6",
    "thm": "#33609B",
    "def": "#20705F",
    "eg": "#8F6218",
    "warn": "#6350A8",
    "rule": "#93A6C4",
    "fillin": "#8E97A3",
}


def _tint(hex_color: str, strength: float = 0.09) -> str:
    """把强调色朝纸白（``_PALETTE["bg"]``）混 ``strength``，得到淡彩底色。

    与 handout_prelude.typ 的 ``tint()`` 同一算法，两边混出来的淡彩底才一致。
    """

    def channels(value: str):
        value = value.lstrip("#")
        return [int(value[position:position + 2], 16) for position in (0, 2, 4)]

    paper = channels(_PALETTE["bg"])
    mixed = [
        round(channel * strength + base * (1 - strength))
        for channel, base in zip(channels(hex_color), paper)
    ]
    return "#%02X%02X%02X" % tuple(mixed)


def _extract_label(text: str) -> Tuple[str, str]:
    """摘掉行尾的 ``<def:x>`` 标签，返回 ``(正文, 标签)``。"""
    match = _LABEL_RE.search(text)
    if not match:
        return text.rstrip(), ""
    return text[: match.start()].rstrip(), match.group(1)


def _split_knot_title(body: str) -> Tuple[str, str]:
    """按 ``标题 —— 正文`` 拆开 knot 的内容。

    标题单独占一行、以 ``——`` 收尾时（正文从下一行开始），残留的破折号不是
    正文的一部分 —— 否则 ``[例] 例 1：… ——`` 会在框里多排一个「—」。
    """
    for separator in ("——", "—", " – ", " - "):
        if separator in body:
            head, rest = body.split(separator, 1)
            if not head.strip():
                continue
            rest = rest.strip()
            if not rest or _DASH_ONLY_RE.match(rest):
                return head.strip(), ""
            return head.strip(), rest
    return "", body.strip()


def _is_marker_start(line: str) -> bool:
    match = _MARKER_BLOCK_RE.match(line.strip())
    return bool(match and match.group(1) in MARKERS)


def _render_inline(
    text: str,
    warnings: List[str],
    image_resolver: Optional[Callable[[str], Tuple[Optional[str], str]]] = None,
    _depth: int = 0,
    refs: Optional[Dict[str, str]] = None,
) -> str:
    """Markdown 行内语法 → Typst markup。

    支持：行内公式、行内代码、**粗体**、*斜体*、~~删除线~~、链接、行内图片、
    ```____`` 填空线、``[缺口: …]``、``@def:x`` 回指。
    其它字符全部按字面量转义。递归深度有上限，避免畸形输入把栈打穿。
    """
    if not text:
        return ""
    if _depth > 8:
        return _escape_inline(text)

    out: List[str] = []
    index = 0
    length = len(text)
    plain: List[str] = []

    def flush() -> None:
        if plain:
            out.append(_escape_inline("".join(plain)))
            plain.clear()

    while index < length:
        char = text[index]

        # 行内公式：$...$（不跨 $$，块级公式在外面处理）。
        # inline=True：`1/r` 这类斜杠在句子里保持平排，不排成顶高行距的分式。
        if char == "$":
            close = text.find("$", index + 1)
            if close != -1 and not text.startswith("$$", index):
                converted, issues = latex_to_typst(text[index + 1:close], inline=True)
                warnings.extend(issues)
                flush()
                out.append(pad_inline_math("$" + converted + "$"))
                index = close + 1
                continue

        # 行内代码
        if char == "`":
            close = text.find("`", index + 1)
            if close != -1:
                flush()
                code = text[index + 1:close]
                out.append("#raw(" + _json_string(code) + ")")
                index = close + 1
                continue

        # 粗体
        if text.startswith("**", index):
            close = text.find("**", index + 2)
            if close != -1 and close > index + 2:
                flush()
                inner = _render_inline(
                    text[index + 2:close], warnings, image_resolver, _depth + 1, refs
                )
                out.append("*" + inner + "*")
                index = close + 2
                continue

        # 删除线
        if text.startswith("~~", index):
            close = text.find("~~", index + 2)
            if close != -1 and close > index + 2:
                flush()
                inner = _render_inline(
                    text[index + 2:close], warnings, image_resolver, _depth + 1, refs
                )
                out.append("#strike[" + inner + "]")
                index = close + 2
                continue

        # 斜体：只认单星号，下划线太容易和标识符冲突，不当作强调。
        if char == "*" and not text.startswith("**", index):
            close = text.find("*", index + 1)
            if close != -1 and close > index + 1:
                flush()
                inner = _render_inline(
                    text[index + 1:close], warnings, image_resolver, _depth + 1, refs
                )
                out.append("_" + inner + "_")
                index = close + 1
                continue

        # 行内图片
        if text.startswith("![", index):
            match = _IMAGE_RE.match(text[index:])
            if match and len(match.group(0)) == len(text) - index:
                if image_resolver is not None:
                    path, warning = image_resolver(match.group(2))
                    if warning:
                        warnings.append(warning)
                    if path:
                        flush()
                        out.append("#image(" + _json_string(path) + ", width: 60%)")
                        index = length
                        continue
                plain.append(match.group(1) or "图片")
                index = length
                continue

        # 行内缺口：[缺口: 关键一步]
        if char == "[":
            gap = _GAP_RE.match(text, index)
            if gap:
                flush()
                out.append(
                    "#gap["
                    + _render_inline(gap.group(1), warnings, image_resolver, _depth + 1, refs)
                    + "]"
                )
                index = gap.end()
                continue

        # 链接
        if char == "[":
            match = _LINK_RE.match(text, index)
            if match:
                flush()
                label = _render_inline(
                    match.group(1), warnings, image_resolver, _depth + 1, refs
                )
                url = match.group(2)
                out.append("#link(" + _json_string(url) + ")[" + label + "]")
                index = match.end()
                continue

        # 回指：@def:x → 指向标签的链接，显示编号。
        if char == "@" and refs is not None:
            match = _REF_RE.match(text, index)
            if match:
                label = match.group(0)[1:]
                flush()
                if label in refs:
                    out.append(
                        "#link(<" + label + ">)[" + _escape_inline(refs[label]) + "]"
                    )
                else:
                    warnings.append(
                        "悬空引用 @" + label + "（没有找到对应的 <" + label + ">）"
                    )
                    out.append(_escape_inline(match.group(0)))
                index = match.end()
                continue

        # 填空线：正文里连续四个以上下划线。
        if char == "_" and text.startswith("____", index):
            end = index
            while end < length and text[end] == "_":
                end += 1
            flush()
            out.append("#fillin(width: 2.2cm)")
            index = end
            continue

        # <br> 换行；其余 HTML 标签丢掉，正文保留。
        if char == "<":
            br = _BR_RE.match(text, index)
            if br:
                flush()
                out.append("#linebreak()")
                index = br.end()
                continue
            tag = _HTML_TAG_RE.match(text, index)
            if tag:
                index = tag.end()
                continue

        plain.append(char)
        index += 1

    flush()
    return "".join(out)


def _render_rich_text(
    text: str,
    warnings: List[str],
    image_resolver,
    refs: Optional[Dict[str, str]] = None,
) -> str:
    """渲染段落文本；硬换行在行内渲染之外拼成 Typst 的 ``#linebreak()``。"""
    if _HARD_BREAK not in text:
        return _render_inline(text, warnings, image_resolver, refs=refs)
    segments = text.split(_HARD_BREAK)
    return "#linebreak()".join(
        _render_inline(segment, warnings, image_resolver, refs=refs)
        for segment in segments
    )


# ------------------------------------------------------------------ 块级渲染


def _paragraph(
    line_text: str,
    warnings: List[str],
    image_resolver,
    refs: Optional[Dict[str, str]] = None,
) -> str:
    return "#h(2em)" + _render_rich_text(line_text, warnings, image_resolver, refs)


def _table_block(
    rows: Sequence[str],
    warnings: List[str],
    image_resolver,
    refs: Optional[Dict[str, str]] = None,
) -> str:
    """表格：三线表（booktabs）风格，只有横线、没有竖线与底色。"""
    parsed: List[List[str]] = []
    for row in rows:
        if _TABLE_SEP_RE.match(row):
            continue
        parsed.append(_split_table_row(row))
    if not parsed:
        return ""
    columns = max(len(row) for row in parsed)
    parsed = [row + [""] * (columns - len(row)) for row in parsed]
    rule = "#9AA7B8"
    lines = [
        "#table(",
        "  columns: " + str(columns) + ",",
        "  inset: (x: 8pt, y: 5pt),",
        "  stroke: none,",
        '  table.hline(stroke: 1pt + rgb("' + rule + '")),',
    ]
    header = parsed[0]
    lines.append(
        "  table.header("
        + ", ".join(
            "[*" + _render_inline(cell, warnings, image_resolver, refs=refs) + "*]"
            for cell in header
        )
        + "),"
    )
    lines.append('  table.hline(stroke: 0.5pt + rgb("' + rule + '")),')
    for row in parsed[1:]:
        lines.append(
            "  " + ", ".join(
                "[" + _render_inline(cell, warnings, image_resolver, refs=refs) + "]"
                for cell in row
            )
            + ","
        )
    lines.append('  table.hline(stroke: 1pt + rgb("' + rule + '")),')
    lines.append(")")
    return "\n".join(lines)


def _quote_block(
    lines: Sequence[str],
    warnings: List[str],
    image_resolver,
    refs: Optional[Dict[str, str]] = None,
) -> str:
    """引用块；GitHub 风格的 ``> [!IMPORTANT]`` 渲染成淡彩提示块。

    引用块里常放「视频来源 + 时间点清单」，必须保留项目符号：把所有行
    揉成一段会把清单压成一行长句（实测很难读）。
    """
    cleaned: List[str] = []
    kind = ""
    for line in lines:
        text = line.strip()
        if text.startswith(">"):
            text = text[1:].lstrip()
        if not cleaned and re.match(r"^\[!(IMPORTANT|WARNING|CAUTION|NOTE|TIP)\]$", text, re.I):
            kind = text[2:-1].upper()
            continue
        cleaned.append(text)

    parts: List[str] = []
    buffer: List[str] = []

    def flush_buffer() -> None:
        """把攒下的引用行接成若干「条目」，条目之间硬换行。

        抬头里的 ``> **来源**：…`` / ``> **上课时间**：…`` 是多行字段；
        逐行接成一段会粘成「时长：约 01:40:16 上课时间：未提供…」，读不出
        哪句是哪句（实地会话里 Agent 只好把抬头改成普通段落）。
        """
        if not buffer:
            return
        items = split_quote_items(buffer)
        buffer.clear()
        rendered = [
            _render_rich_text(_join_paragraph(item), warnings, image_resolver, refs)
            for item in items
        ]
        parts.append("#linebreak()".join(part for part in rendered if part.strip()))

    index = 0
    while index < len(cleaned):
        text = cleaned[index]
        if _LIST_RE.match(text):
            flush_buffer()
            list_lines: List[str] = []
            while index < len(cleaned) and _LIST_RE.match(cleaned[index]):
                list_lines.append(cleaned[index])
                index += 1
            parts.append(_list_block(list_lines, warnings, image_resolver, refs))
            continue
        buffer.append(text)
        index += 1
    flush_buffer()
    body = "\n\n".join(part for part in parts if part.strip())

    label, tone = {
        "IMPORTANT": ("重点", "thm"),
        "WARNING": ("注意", "warn"),
        "CAUTION": ("注意", "warn"),
        "NOTE": ("说明", "def"),
        "TIP": ("提示", "def"),
    }.get(kind, ("", "thm"))
    if kind == "IMPORTANT":
        # 「重点」不再套方框：走 prelude 的 keypoint —— 规范蓝色的文字段落，
        # 只保留首行缩进与段距，没有底色 / 左侧竖线。
        return "#keypoint[*" + label + "*　" + body + "]"
    if kind:
        accent = _PALETTE[tone]
        return (
            "#block(\n"
            "  inset: (x: 12pt, y: 9pt),\n"
            '  fill: rgb("' + _tint(accent) + '"),\n'
            '  stroke: (left: 2.5pt + rgb("' + accent + '")),\n'
            ")[" + "*" + label + "*　" + body + "]"
        )
    return (
        "#block(\n"
        "  inset: (left: 12pt, y: 3pt),\n"
        '  stroke: (left: 2pt + rgb("' + _PALETTE["hairline"] + '")),\n'
        '  text(fill: rgb("' + _PALETTE["muted"] + '"))[' + body + "]\n"
        ")"
    )


def _list_block(
    lines: Sequence[str],
    warnings: List[str],
    image_resolver,
    refs: Optional[Dict[str, str]] = None,
) -> str:
    out: List[str] = []
    for line in lines:
        match = _LIST_RE.match(line)
        if not match:
            continue
        indent, marker, body = match.group(1), match.group(2), match.group(3)
        level = min(3, len(indent.expandtabs(4)) // 2)
        bullet = "-" if marker in ("-", "*", "+") else "+"
        body = re.sub(
            r"^\[([ xX])\]\s*",
            lambda m: "☑ " if m.group(1).lower() == "x" else "☐ ",
            body,
        )
        out.append(
            "  " * level + bullet + " "
            + _render_inline(body, warnings, image_resolver, refs=refs)
        )
    return "\n".join(out)


def _code_block(fence: str, info: str, body: Sequence[str]) -> str:
    language = (info or "").strip().split()[0] if (info or "").strip() else ""
    content = "\n".join(body)
    args = [_json_string(content), "block: true"]
    if language:
        args.append("lang: " + _json_string(language))
    return "#raw(" + ", ".join(args) + ")"


def _image_block(
    alt: str,
    source: str,
    warnings: List[str],
    image_resolver,
    refs: Optional[Dict[str, str]] = None,
) -> str:
    path, warning = image_resolver(source)
    if warning:
        warnings.append(warning)
    if not path:
        return "#aside(" + _json_string("图片未嵌入：" + (alt or source)) + ")"
    caption = (
        "caption: [" + _render_inline(alt, warnings, image_resolver, refs=refs) + "]"
        if alt
        else ""
    )
    figure_args = ["image(" + _json_string(path) + ", width: 100%)"]
    if caption:
        figure_args.append(caption)
    return "#figure(" + ", ".join(figure_args) + ")"


def _read_display_math(
    lines: Sequence[str],
    index: int,
    warnings: List[str],
) -> Tuple[str, int]:
    """从 ``lines[index]`` 的 ``$$`` 开始读一个块级公式。

    返回 ``(Typst 片段, 下一个待处理下标)``；块级公式以 ``$ … $``（两侧
    有空白）输出，Typst 才会把它当居中块级公式。
    """
    body = [lines[index].strip()[2:]]
    index += 1
    total = len(lines)
    if "$$" in body[0]:
        inner = body[0].split("$$")[0]
    else:
        while index < total:
            line = lines[index].strip()
            index += 1
            if "$$" in line:
                body.append(line.split("$$")[0])
                break
            body.append(line)
        inner = "\n".join(body)
    converted, issues = latex_to_typst(inner.strip())
    warnings.extend(issues)
    return "$ " + converted.strip() + " $", index


def _absorbs_blocks(name: str) -> bool:
    """标记块是否**跨段**：框类装置与证明一直写到下一个标记/标题。

    ``[直觉]`` / ``[练习]`` / ``[边注]`` / ``[强调]`` 这类装置是一句话，
    只吃标记行那一句；定理、定义、例、证明的正文常常带块级公式与多个
    段落，旧实现遇到空行或 ``$$`` 就收尾，公式会被甩到方框外，证明的
    qed 方块也会停在第一段末尾（实地讲义里就是这样误导读者的）。
    """
    call, _shape = MARKERS[name]
    return call == "proof" or call in _KNOT_CALLS


def _collect_marker_body(
    lines: Sequence[str],
    index: int,
    first: str,
    absorb: bool,
    proof: bool = False,
) -> Tuple[List[str], int]:
    """收集标记行之后的正文行，返回 ``(行列表, 下一个待处理下标)``。

    ``absorb=False`` 沿用旧规则：遇到空行、标题、公式、列表、表格、代码块
    或下一个标记就停。``absorb=True`` 一直收到下一个标题 / 标记 / 新话题，
    空行保留为段落分隔；``proof=True`` 时不把「短引导词 + 时间码」当边界，
    免得证明被从中间截断。
    """
    body: List[str] = [first] if first else []
    total = len(lines)
    if absorb:
        while index < total:
            raw = lines[index]
            stripped = raw.strip()
            if block_boundary(stripped, proof=proof):
                break
            body.append(raw)
            index += 1
    else:
        while index < total:
            candidate = lines[index].strip()
            if (
                not candidate
                or _HEADING_RE.match(candidate)
                or _is_marker_start(candidate)
                or candidate.startswith("$$")
                or _LIST_RE.match(lines[index])
                or candidate.startswith("|")
                or _FENCE_RE.match(candidate)
            ):
                break
            body.append(candidate)
            index += 1
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return body, index


def _extract_block_label(body: List[str]) -> Tuple[List[str], str]:
    """摘掉块里的 ``<def:x>``，返回 ``(正文行, label)``。

    认三个位置：标记行末尾（最常见）、独占一行的 ``<label>``、最后一段末尾。
    跨段标记把 ``<label>`` 写在公式后面单独一行也很自然，三种都认，
    才能和 :func:`_collect_refs` 的编号对得上。
    """
    if body:
        text, label = _extract_label(body[0])
        if label:
            return [text] + list(body[1:]), label
    for position, raw in enumerate(body):
        stripped = raw.strip()
        if not stripped:
            continue
        text, label = _extract_label(stripped)
        if not label or text.strip():
            continue
        rest = list(body)
        del rest[position]
        return rest, label
    for position in range(len(body) - 1, -1, -1):
        if not body[position].strip():
            continue
        text, label = _extract_label(body[position])
        if not label:
            break
        rest = list(body)
        rest[position] = text
        if not text.strip():
            del rest[position]
        return rest, label
    return list(body), ""


def _split_knot_title_lines(body: List[str]) -> Tuple[str, List[str]]:
    """只在**第一段**里找 ``标题 —— 正文``；后面的段落原样保留。"""
    if not body:
        return "", []
    title, rest = _split_knot_title(_join_paragraph([body[0]]))
    if not title:
        return "", list(body)
    remainder = list(body[1:])
    if rest.strip():
        return title, [rest] + remainder
    return title, remainder


def _render_block_sequence(
    lines: Sequence[str],
    warnings: List[str],
    image_resolver,
    refs: Optional[Dict[str, str]] = None,
) -> Tuple[str, int]:
    """把标记块里的若干行渲染成 Typst 块序列（块内段落不缩进）。

    与 :func:`_render_body` 的区别：不处理标题、不统计章节、不写段首缩进
    （``#h(2em)``）—— 这些内容会作为 ``#theorem{…}`` / ``#proof{…}`` 的
    内容块嵌进装置里，缩进交给装置自己的内边距。

    返回 ``(Typst 内容, 段落数)``：段落数记进「方框:正文」统计，否则内容
    一搬进装置，分母就凭空变小，比例检查会误报。
    """
    out: List[str] = []
    paragraph: List[str] = []
    paragraphs = 0
    total = len(lines)
    index = 0

    def flush() -> None:
        nonlocal paragraphs
        if not paragraph:
            return
        text = _join_paragraph(paragraph)
        paragraph.clear()
        if not text.strip():
            return
        # 「题目 / 切入点 / 关键步骤 / 易错点」写在同一段里时，一段一行排开：
        # 四段式例题排成一大坨在框里很难读（实地讲义里就是这样）。
        for part in split_review_labels(text):
            out.append(_render_rich_text(part, warnings, image_resolver, refs))
            paragraphs += 1

    while index < total:
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            flush()
            index += 1
            continue
        if stripped.startswith("$$"):
            flush()
            math, index = _read_display_math(lines, index, warnings)
            out.append(math)
            continue
        if _LIST_RE.match(raw):
            flush()
            list_lines: List[str] = []
            while index < total and _LIST_RE.match(lines[index]):
                list_lines.append(lines[index])
                index += 1
            out.append(_list_block(list_lines, warnings, image_resolver, refs))
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            rows: List[str] = []
            while index < total:
                candidate = lines[index].strip()
                if candidate.startswith("|") and candidate.endswith("|"):
                    rows.append(candidate)
                    index += 1
                else:
                    break
            if len(rows) >= 2 and _TABLE_SEP_RE.match(rows[1]):
                flush()
                out.append(_table_block(rows, warnings, image_resolver, refs))
            else:
                paragraph.extend(rows)
            continue
        if stripped.startswith(">"):
            flush()
            quote_lines: List[str] = []
            while index < total and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index])
                index += 1
            out.append(_quote_block(quote_lines, warnings, image_resolver, refs))
            continue
        fence = _FENCE_RE.match(stripped)
        if fence:
            flush()
            marker_text = fence.group(1)
            info = fence.group(2) or ""
            code: List[str] = []
            index += 1
            while index < total and not lines[index].strip().startswith(marker_text[:3]):
                code.append(lines[index])
                index += 1
            if index < total:
                index += 1
            out.append(_code_block(marker_text, info, code))
            continue
        image = _IMAGE_RE.match(stripped)
        if image:
            flush()
            out.append(
                _image_block(
                    image.group(1), image.group(2), warnings, image_resolver, refs
                )
            )
            index += 1
            continue
        paragraph.append(raw)
        index += 1

    flush()
    return "\n\n".join(part for part in out if part.strip()), paragraphs


def _render_marker_block(
    name: str,
    body_lines: Sequence[str],
    number: str,
    warnings: List[str],
    image_resolver,
    refs: Optional[Dict[str, str]] = None,
) -> Tuple[str, int]:
    """把一个标记块（标记行 + 后续正文）渲染成对应的 PDF 装置。

    返回 ``(Typst 片段, 块内段落数)``；段落数并入全篇的「方框:正文」统计。
    """
    call, shape = MARKERS[name]
    if call is None:
        return "#divider", 0
    body, label = _extract_block_label(list(body_lines))
    if shape == "knot":
        title, content = _split_knot_title_lines(body)
        args = [_json_string(number)]
        if title:
            args.append(
                "title: ["
                + _render_inline(title, warnings, image_resolver, refs=refs)
                + "]"
            )
        content_typst, paragraphs = _render_block_sequence(
            content, warnings, image_resolver, refs
        )
        fragment = "#" + call + "(" + ", ".join(args) + ")[" + content_typst + "]"
    else:
        if call == "yourturn":
            # 练习块里已经有书写横线，题面里的短填空线一并丢掉（见规范 §2.1）。
            body = [re.sub(r"_{4,}", " ", line) for line in body]
        content_typst, paragraphs = _render_block_sequence(
            body, warnings, image_resolver, refs
        )
        if call == "sidenote":
            # 边注的符号必须用圆括号参数；方括号写法会被当成第二个内容块。
            fragment = "#sidenote([" + content_typst + "], symbol: [!])"
        else:
            fragment = "#" + call + "[" + content_typst + "]"
    if label:
        fragment += " <" + label + ">"
    return fragment, paragraphs


def _is_block_start(line: str) -> bool:
    stripped = line.strip()
    return bool(
        not stripped
        or _HEADING_RE.match(stripped)
        or stripped.startswith("$$")
        or _FENCE_RE.match(stripped)
        or _LIST_RE.match(line)
        or stripped.startswith(">")
        or _HR_RE.match(stripped)
        or _TABLE_SEP_RE.match(stripped)
        or (stripped.startswith("|") and stripped.endswith("|"))
        or _IMAGE_RE.match(stripped)
        or _is_marker_start(stripped)
        or _UNKNOWN_MARKER_RE.match(stripped)
        or stripped.lower().startswith("<details")
        or stripped.lower().startswith("</details")
    )


def _collect_refs(lines: Sequence[str]) -> Dict[str, str]:
    """先扫一遍正文，收集 ``<label>`` → 编号。

    编号必须和 :func:`_render_body` 完全一致：一级标题进一节，knot 按类型
    在该节内从 1 开始数。这样 ``@def:x`` 才能显示出真正的「2.1」。
    """
    refs: Dict[str, str] = {}
    section = 0
    sub = 0
    counts: Dict[str, int] = {}

    index = 0
    total = len(lines)
    while index < total:
        raw = lines[index]
        stripped = raw.strip()
        index += 1
        if not stripped:
            continue
        heading = _HEADING_RE.match(stripped)
        if heading:
            level = len(heading.group(1))
            title, label = _extract_label(heading.group(2).strip())
            if level <= 2:
                section += 1
                sub = 0
                counts.clear()
            elif level == 3:
                sub += 1
            if label:
                if level <= 2:
                    refs[label] = str(section)
                elif level == 3:
                    refs[label] = str(section) + "." + str(sub)
                else:
                    refs[label] = str(section)
            continue
        marker = _MARKER_BLOCK_RE.match(stripped)
        if not marker:
            continue
        name = marker.group(1)
        if name not in MARKERS:
            continue
        call, _shape = MARKERS[name]
        if call not in _KNOT_CALLS:
            continue
        # 与 _render_body 用同一个收集器：框可以跨段，<label> 也可能写在
        # 最后一段末尾；两处必须同进同退，编号才不会漂。
        body_lines, index = _collect_marker_body(
            lines, index, marker.group(2), _absorbs_blocks(name), name == "证明"
        )
        counts["knot"] = counts.get("knot", 0) + 1
        number = (str(section) + "." if section else "") + str(counts["knot"])
        _body, label = _extract_block_label(body_lines)
        if label:
            refs[label] = number
    return refs


def _render_body(
    lines: Sequence[str],
    warnings: List[str],
    image_resolver,
    blocks: Dict[str, int],
    refs: Optional[Dict[str, str]] = None,
) -> Tuple[str, int]:
    """逐块渲染 Markdown 正文，返回 ``(Typst 正文, 章节数)``。"""
    out: List[str] = []
    sections = 0
    index = 0
    total = len(lines)
    refs = refs or {}
    section = 0
    counts: Dict[str, int] = {}
    section_name = ""
    boxes_by_section: Dict[str, int] = {}
    question_count = 0

    def count(name: str, amount: int = 1) -> None:
        blocks[name] = blocks.get(name, 0) + amount

    while index < total:
        raw = lines[index]
        stripped = raw.strip()

        if not stripped:
            index += 1
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            level = len(heading.group(1))
            title, label = _extract_label(heading.group(2).strip())
            title = strip_heading_number(title)
            # 讲义标题已进封面；正文从 H2 开始，H2 映射成 Typst 一级标题。
            if level <= 2:
                section += 1
                counts.clear()
                section_name = title
                boxes_by_section.setdefault(section_name, 0)
            elif level == 3:
                # 「每节」按最小小节算：`## 二、分章详解` 下面挂 7 个
                # `### 2.1 …`，按 h2 统计会把 7 小节的框算成同一节。
                section_name = title
                boxes_by_section.setdefault(section_name, 0)
            typst_level = max(1, level - 1)
            if level <= 2:
                sections += 1
            rendered = _render_inline(title, warnings, image_resolver, refs=refs)
            out.append(
                "=" * typst_level + " " + rendered + (" <" + label + ">" if label else "")
            )
            count("heading")
            index += 1
            continue

        # 底稿标记：直觉 / 定义 / 定理 / 例 / 证明 / 练习 / 边注 / 强调 / 分隔 …
        marker = _MARKER_BLOCK_RE.match(stripped)
        if marker and marker.group(1) in MARKERS:
            name = marker.group(1)
            body_lines, index = _collect_marker_body(
                lines, index + 1, marker.group(2), _absorbs_blocks(name), name == "证明"
            )
            call, _shape = MARKERS[name]
            number = ""
            if call in _KNOT_CALLS:
                counts["knot"] = counts.get("knot", 0) + 1
                number = (str(section) + "." if section else "") + str(counts["knot"])
                boxes_by_section[section_name] = boxes_by_section.get(section_name, 0) + 1
            fragment, inner_paragraphs = _render_marker_block(
                name, body_lines, number, warnings, image_resolver, refs
            )
            out.append(fragment)
            if inner_paragraphs:
                # 块内段落也算进「方框:正文」的分母：内容搬进装置之后，
                # 分母不能凭空变小，否则比例检查会把正常的讲义判成框框滥用。
                count("paragraph", inner_paragraphs)
            count(call or name)
            continue

        # 未知的中文标记（`[推导] …`）：推导按旧规范的 Proof 排（斜体 Proof. +
        # 块末 qed，跨段、不套框）；其余未知标记按加粗小标题兜底。
        unknown = _UNKNOWN_MARKER_RE.match(stripped)
        if unknown:
            if unknown.group(1) == "推导":
                body_lines, index = _collect_marker_body(
                    lines, index + 1, unknown.group(2), True, True
                )
                fragment, inner_paragraphs = _render_marker_block(
                    "证明", body_lines, "", warnings, image_resolver, refs
                )
                out.append(fragment)
                if inner_paragraphs:
                    count("paragraph", inner_paragraphs)
                count("proof")
                continue
            lead = "**" + unknown.group(1) + "**"
            if unknown.group(2):
                lead += "　" + unknown.group(2)
            out.append(_paragraph(lead, warnings, image_resolver, refs))
            count("paragraph")
            index += 1
            continue

        # 自测题的答案块：`<details><summary>答案</summary>…</details>`。
        # 题干已在上面的段落分支里套成 `#selftest` 琥珀框；答案排在框外，
        # 用 `#answer`（左侧淡灰细线 + 标签）与题目分开。
        if stripped.lower().startswith("<details"):
            index += 1
            label = "答案"
            content: List[str] = []
            while index < total:
                candidate = lines[index]
                text_line = candidate.strip()
                if text_line.lower().startswith("</details"):
                    index += 1
                    break
                summary = _SUMMARY_LINE_RE.search(text_line)
                if summary:
                    label = summary.group(1).strip() or label
                    index += 1
                    continue
                content.append(candidate)
                index += 1
            content_typst, inner = _render_block_sequence(
                content, warnings, image_resolver, refs
            )
            out.append("#answer(" + _json_string(label) + ")[" + content_typst + "]")
            count("answer")
            if inner:
                count("paragraph", inner)
            continue

        fence = _FENCE_RE.match(stripped)
        if fence:
            marker_text = fence.group(1)
            info = fence.group(2) or ""
            body = []
            index += 1
            while index < total and not lines[index].strip().startswith(marker_text[:3]):
                body.append(lines[index])
                index += 1
            if index < total:
                index += 1
            out.append(_code_block(marker_text, info, body))
            count("code")
            continue

        if stripped.startswith("$$"):
            math, index = _read_display_math(lines, index, warnings)
            out.append(math)
            count("equation")
            continue

        if _HR_RE.match(stripped):
            out.append("#divider")
            count("divider")
            index += 1
            continue

        if _IMAGE_RE.match(stripped):
            match = _IMAGE_RE.match(stripped)
            out.append(
                _image_block(match.group(1), match.group(2), warnings, image_resolver, refs)
            )
            count("image")
            index += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            table_rows: List[str] = []
            while index < total:
                candidate = lines[index].strip()
                if candidate.startswith("|") and candidate.endswith("|"):
                    table_rows.append(candidate)
                    index += 1
                else:
                    break
            # 只有第二行是分隔线时才当表格；否则退化回段落。
            if len(table_rows) >= 2 and _TABLE_SEP_RE.match(table_rows[1]):
                out.append(_table_block(table_rows, warnings, image_resolver, refs))
                count("table")
            else:
                out.append(
                    _paragraph(_join_paragraph(table_rows), warnings, image_resolver, refs)
                )
                count("paragraph")
            continue

        if _LIST_RE.match(raw):
            list_lines: List[str] = []
            while index < total:
                line = lines[index]
                if _LIST_RE.match(line):
                    list_lines.append(line)
                    index += 1
                    continue
                candidate = line.strip()
                if not candidate or _is_block_start(line):
                    break
                # Markdown 的惰性续行：接到上一条列表项后面。否则一条
                # 换行会把有序列表截断成两个，编号又从 1 开始。
                if list_lines:
                    list_lines[-1] = _join_paragraph([list_lines[-1], line])
                index += 1
            out.append(_list_block(list_lines, warnings, image_resolver, refs))
            count("list")
            continue

        if stripped.startswith(">"):
            quote_lines: List[str] = []
            while index < total and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index])
                index += 1
            out.append(_quote_block(quote_lines, warnings, image_resolver, refs))
            count("quote")
            continue

        # 普通段落：吃掉直到空行或下一个块级结构。
        paragraph: List[str] = [raw]
        index += 1
        while index < total and not _is_block_start(lines[index]):
            paragraph.append(lines[index])
            index += 1
        text = _join_paragraph(paragraph)
        # 紧跟 `<details>` 的段落是自测题题干：套进与「例」同款的琥珀方框，
        # 答案就会排在框外，题目与答案之间有一道清楚的边界。
        probe = index
        while probe < total and not lines[probe].strip():
            probe += 1
        if probe < total and lines[probe].strip().lower().startswith("<details"):
            number, stem = split_question_number(text)
            if number:
                question_count = max(question_count, int(number))
            else:
                question_count += 1
                number = str(question_count)
            out.append(
                "#selftest(" + number + ")["
                + _render_rich_text(stem, warnings, image_resolver, refs)
                + "]"
            )
            count("selftest")
            count("paragraph")
            continue
        out.append(_paragraph(text, warnings, image_resolver, refs))
        count("paragraph")

    for name, boxes in boxes_by_section.items():
        if boxes > KNOT_BUDGET_PER_SECTION:
            warnings.append(
                "第「" + (name or "未命名") + "」节有 " + str(boxes) + " 个方框，"
                "超过每节 " + str(KNOT_BUDGET_PER_SECTION) + " 个的视觉预算；"
                "按格式规范，把不需要被回指的那几条降级成普通段落 + [强调] 行内强调"
            )

    return "\n\n".join(item for item in out if item.strip()), sections


# ------------------------------------------------------------------- 封面


def _extract_cover(
    markdown: str,
    title: str,
    subtitle: str,
    author: str,
    date: str,
    kicker: str,
) -> Tuple[List[str], Dict[str, str]]:
    """摘出封面；返回 ``(去掉封面后的行, 封面字段)``。"""
    lines = markdown.replace("\r\n", "\n").split("\n")
    fields: Dict[str, str] = {}
    body: List[str] = []
    in_cover = False
    consumed_h1 = False

    for line in lines:
        stripped = line.strip()
        heading = _HEADING_RE.match(stripped)
        if heading:
            level = len(heading.group(1))
            head = heading.group(2).strip()
            if level == 1 and head in ("封面", "Cover", "cover"):
                in_cover = True
                continue
            if in_cover:
                in_cover = False
            if level == 1 and not consumed_h1:
                # 第一个 H1 是讲义标题，交给封面；不再在正文里重复一遍。
                # 即使调用方显式传了 title，也要把它从正文摘掉（否则会双标题）。
                if not title:
                    title = head
                consumed_h1 = True
                continue
        if in_cover:
            item = re.match(r"^-\s*([A-Za-z_]+)\s*:\s*(.*)$", stripped)
            if item:
                fields[item.group(1).lower()] = item.group(2).strip()
            continue
        body.append(line)

    fields["title"] = title or fields.get("title", "")
    fields["subtitle"] = subtitle or fields.get("subtitle", "")
    fields["author"] = author or fields.get("author", "")
    fields["date"] = date or fields.get("date", "")
    fields["kicker"] = kicker or fields.get("kicker", "")

    # 标题里带副题时拆开：「复变函数 第 3 讲：留数定理」
    if fields["title"] and not fields["subtitle"]:
        for separator in ("：", "——", " - "):
            if separator in fields["title"]:
                main, rest = fields["title"].split(separator, 1)
                if main.strip() and rest.strip():
                    fields["title"] = main.strip()
                    fields["subtitle"] = rest.strip()
                    break
    return body, fields


def _cover_typst(fields: Dict[str, str]) -> str:
    title = fields.get("title", "").strip()
    if not title:
        return ""
    args = [_json_string(title)]
    for key in ("subtitle", "author", "date", "kicker"):
        value = fields.get(key, "").strip()
        if value:
            args.append(f"{key}: " + _json_string(value))
    return "#cover(" + ", ".join(args) + ")"


# --------------------------------------------------------------------- 入口


def render_handout(
    markdown: str,
    title: str = "",
    subtitle: str = "",
    author: str = "",
    date: str = "",
    kicker: str = "ZJU · 智云课堂",
    theme: str = "light",
    workspace_root: str = "",
    note_path: str = "",
    toc: bool = True,
) -> HandoutResult:
    """把一份讲义 Markdown 渲染成 ``main.typ``。

    ``workspace_root`` 是 Typst 的 ``--root``，也是图片可读范围的边界；
    ``note_path`` 用来解析相对图片路径。二者都不要求存在。
    ``theme`` 目前只接受 ``light`` / ``dark`` 作为参数校验；讲义模板固定为
    淡色阅读版（深色版留给填空笔记）。
    """
    if theme not in ("light", "dark"):
        raise StudyNotesError(f"theme 只能是 light / dark，收到 {theme!r}")

    warnings: List[str] = []
    cleaned = _HTML_COMMENT_RE.sub("", markdown.replace("\r\n", "\n"))
    # `<details>` / `<summary>` 不再预先摊平：自测题的题干与答案要分别排成
    # `#selftest`（琥珀框）与 `#answer`（框外、灰色左线），见 _render_body。

    body_lines, fields = _extract_cover(
        cleaned, title=title, subtitle=subtitle, author=author, date=date, kicker=kicker
    )
    # 没有封面标题时，不能整份文档只有小节；把第一个 H1 当正文标题。
    if not fields.get("title"):
        for line in body_lines:
            heading = _HEADING_RE.match(line.strip())
            if heading and len(heading.group(1)) == 1:
                fields["title"] = heading.group(2).strip()
                break

    note_dir = os.path.dirname(os.path.abspath(note_path)) if note_path else os.getcwd()
    root = workspace_root or note_dir

    def image_resolver(source: str) -> Tuple[Optional[str], str]:
        return _resolve_image(source, note_dir, root)

    # 先扫一遍标签，再渲染：这样 @def:x 能显示真正的编号（含前向引用）。
    refs = _collect_refs(body_lines)
    blocks: Dict[str, int] = {}
    body_typst, sections = _render_body(
        body_lines, warnings, image_resolver, blocks, refs
    )

    # 格式规范的「方框 : 正文段落」检查（§2.3）：超过 1:4 判为框框滥用。
    boxes = sum(blocks.get(call, 0) for call in _KNOT_CALLS)
    paragraphs = blocks.get("paragraph", 0)
    if boxes and paragraphs >= 8 and boxes * 4 > paragraphs:
        warnings.append(
            "方框:正文 = " + str(boxes) + ":" + str(paragraphs)
            + "，超过 1:4 的滥用线；按格式规范，只框住真正被回指的那几条，"
            "其余写成普通段落 + [强调]"
        )

    pieces: List[str] = [_handout_prelude_text()]
    if fields.get("title"):
        # PDF 阅读器标题栏/书签里显示课程名，而不是文件名。
        pieces.append("#set document(title: " + _json_string(fields["title"]) + ")")
    cover = _cover_typst(fields)
    if cover:
        # 模板里的 cover() 自己会换页并把页码重置为 1。
        pieces.append(cover)
    if cover and toc and sections >= 3:
        pieces.append("#toc(depth: 2)")
    if body_typst:
        pieces.append(body_typst)

    typst = "\n\n".join(piece for piece in pieces if piece.strip()) + "\n"
    return HandoutResult(
        typst=typst,
        warnings=warnings,
        title=fields.get("title", ""),
        subtitle=fields.get("subtitle", ""),
        date=fields.get("date", ""),
        sections=sections,
        blocks=blocks,
    )


def _pdf_page_count(path: str) -> int:
    """数 PDF 里的页面对象；读不出来时返回 0（不猜）。"""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return 0
    count = len(re.findall(rb"/Type\s*/Page\b", data))
    return count


def compile_handout(
    typst_source: str,
    output_pdf: str,
    workspace_root: str,
    build_dir: str = "",
    timeout: int = 180,
) -> HandoutCompileResult:
    """编译讲义 PDF。

    ``build_dir`` 只放自包含的 ``main.typ``；默认在工作区的
    ``.zju-lecture/handout/<输出名>/`` 下。PDF 先编译到构建目录，再原子替换
    目标文件，避免编译失败时留下半个 PDF。
    """
    # Typst 自举：环境变量 → 插件缓存 → PATH；缺失时按设置自动下载。
    # 失败只影响 PDF（Markdown 已保存），所以返回结果而不是抛异常。
    from .deps import auto_install_enabled, compile_args, probe

    root = os.path.abspath(workspace_root or os.getcwd())
    info = probe(auto_install=auto_install_enabled())
    if not info.ok or not info.path:
        detail = "；".join(info.notes) if info.notes else "原因未识别"
        return HandoutCompileResult(
            ok=False,
            errors=[
                f"找不到 typst：{detail}。Markdown 已保存；"
                "运行 zju_doctor(install=true) 自动安装，或设置 ZJU_TYPST_BIN 后重试。"
            ],
        )
    typst = info.path
    shared = compile_args(root)

    root = os.path.abspath(workspace_root or os.getcwd())
    output_pdf = os.path.abspath(output_pdf)
    if not build_dir:
        stem = os.path.splitext(os.path.basename(output_pdf))[0]
        safe = re.sub(r'[\\/:*?"<>|\s]+', "-", stem) or "handout"
        build_dir = os.path.join(root, BUILD_DIR_NAME, "handout", safe)
    build_dir = os.path.abspath(build_dir)
    os.makedirs(build_dir, exist_ok=True)

    main_path = os.path.join(build_dir, "main.typ")
    try:
        with open(main_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(typst_source)
    except OSError as exc:
        return HandoutCompileResult(ok=False, errors=[f"写入 Typst 工程失败：{exc}"])

    built_pdf = os.path.join(build_dir, "out.pdf")
    code, output = _run_typst(
        typst,
        ["compile", *shared, "--root", root, "main.typ", "out.pdf"],
        build_dir,
        timeout,
    )
    errors = [line for line in output.splitlines() if "error:" in line]
    warnings = [
        line for line in output.splitlines()
        if "warning:" in line and "unknown font family" not in line
    ]
    if code != 0 and not errors:
        errors.append(f"typst 退出码 {code}")

    if code != 0 or not os.path.isfile(built_pdf):
        return HandoutCompileResult(
            ok=False,
            errors=errors or ["typst 没有产出 PDF（原因未识别）"],
            warnings=warnings,
            output=output,
        )

    try:
        os.makedirs(os.path.dirname(output_pdf), exist_ok=True)
        temporary = output_pdf + ".tmp"
        shutil.copyfile(built_pdf, temporary)
        os.replace(temporary, output_pdf)
    except OSError as exc:
        return HandoutCompileResult(
            ok=False,
            errors=[f"PDF 已编译但复制到目标位置失败：{exc}"],
            warnings=warnings,
            output=output,
        )

    return HandoutCompileResult(
        ok=True,
        pdf_path=output_pdf,
        pages=_pdf_page_count(output_pdf),
        warnings=warnings,
        output=output,
    )


def compile_handout_file(
    note_path: str,
    note_text: str,
    output_pdf: str = "",
    title: str = "",
    subtitle: str = "",
    date: str = "",
    workspace_root: str = "",
    toc: bool = True,
) -> HandoutCompileResult:
    """读一份讲义文本 → 渲染 → 编译 PDF 的便捷入口。"""
    note_path = os.path.abspath(note_path)
    if not output_pdf:
        output_pdf = os.path.splitext(note_path)[0] + ".pdf"
    rendered = render_handout(
        note_text,
        title=title,
        subtitle=subtitle,
        date=date,
        workspace_root=workspace_root,
        note_path=note_path,
        toc=toc,
    )
    result = compile_handout(
        rendered.typst,
        output_pdf,
        workspace_root=workspace_root or os.path.dirname(note_path),
    )
    # 渲染阶段的可读性提示也并入结果，调用方一次就能看全。
    if rendered.warnings:
        result.warnings = list(rendered.warnings) + list(result.warnings)
    return result
