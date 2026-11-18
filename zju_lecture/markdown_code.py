"""Markdown 代码边界与代码块渲染：两条 PDF 链路和 note_lint 共用一份判据。

围栏（``` / ~~~，按字符与长度配平）和行内代码（多反引号配平）里的内容是示例，
不是正文：数学转换、HTML 注释清理、机械修复都不能改写它，标题/标签扫描也不能
把代码里的 ``# 注释`` 当成文档结构。早先三处各自维护一套 ``in_fence`` 翻转，
遇到 ````markdown 里嵌 ```latex 这类嵌套围栏就互相打架，这里收敛成单一来源。
"""

import json
import re
from typing import Callable, Iterable, Iterator, List, Optional, Sequence, Tuple

#: 行内代码：两端是相同数量、完整的一段反引号（``a ` b`` 需要双反引号包裹）。
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)")

_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})([^\r\n]*)[\r\n]*$")


def opening_fence(line: str) -> Optional[Tuple[str, str]]:
    """识别围栏起始行，返回 ``(围栏标记, 信息串)``；不是起始行返回 ``None``。"""
    match = _FENCE_RE.match(line)
    # 反引号围栏的信息串里不能再有反引号（CommonMark），否则它不是合法起始行。
    if not match or (match.group(1)[0] == "`" and "`" in match.group(2)):
        return None
    return match.group(1), match.group(2).strip()


def is_fence_close(line: str, marker: str) -> bool:
    """闭合围栏：同种字符、长度不少于起始标记、整行只有该字符。"""
    stripped = line.strip()
    return len(stripped) >= len(marker) and set(stripped) == {marker[0]}


def fenced_line_flags(lines: Iterable[str]) -> Iterator[bool]:
    """逐行标记是否落在围栏代码内（含起始行与闭合行）。"""
    marker = ""
    for line in lines:
        if marker:
            if is_fence_close(line, marker):
                marker = ""
            yield True
        else:
            opening = opening_fence(line)
            if opening:
                marker = opening[0]
            yield bool(opening)


def transform_prose(text: str, transform: Callable[[str], str]) -> str:
    """只对正文跑 ``transform``，围栏与行内代码逐字节保留。

    正文段先摘出行内代码换成唯一占位符再转换，转完恢复；围栏整段跳过。
    占位符前缀若与原文冲突就加长，保证恢复时不会顶掉真实内容。
    """
    prefix = "\x00ZJU-CODE\x00"
    while prefix in text:
        prefix += "\x00"
    out: List[str] = []
    prose: List[str] = []

    def flush() -> None:
        if not prose:
            return
        kept: List[Tuple[str, str]] = []

        def protect(match: "re.Match[str]") -> str:
            token = f"{prefix}{len(kept)}\x00"
            kept.append((token, match.group(0)))
            return token

        protected = INLINE_CODE_RE.sub(protect, "".join(prose))
        rewritten = transform(protected)
        for token, original in kept:
            rewritten = rewritten.replace(token, original)
        out.append(rewritten)
        prose.clear()

    lines = text.splitlines(keepends=True)
    for line, is_code in zip(lines, fenced_line_flags(lines)):
        if is_code:
            flush()
            out.append(line)
        else:
            prose.append(line)
    flush()
    return "".join(out)


def code_block_typst(body: Sequence[str], info: str = "") -> str:
    """围栏代码 → Typst ``#raw(..., block: true)``，内容逐字节保留。"""
    args = [json.dumps("\n".join(body), ensure_ascii=False), "block: true"]
    language = info.strip().split()[0] if info.strip() else ""
    if language:
        args.append("lang: " + json.dumps(language, ensure_ascii=False))
    return "#raw(" + ", ".join(args) + ")"