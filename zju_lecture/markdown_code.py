"""Shared code boundaries for Markdown rendering and mechanical rewrites."""
import re
from typing import Callable, Iterable, Iterator, Optional, Tuple


# Both ends must be an entire run of the same number of backticks.
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)")
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})([^\r\n]*)[\r\n]*$")


def opening_fence(line: str) -> Optional[Tuple[str, str]]:
    match = _FENCE_RE.match(line)
    if not match or (match.group(1)[0] == "`" and "`" in match.group(2)):
        return None
    return match.group(1), match.group(2).strip()


def is_fence_close(line: str, marker: str) -> bool:
    stripped = line.strip()
    return (len(stripped) >= len(marker)
            and bool(stripped) and set(stripped) == {marker[0]})


def fenced_line_flags(lines: Iterable[str]) -> Iterator[bool]:
    """Flag complete fenced ranges, including their opening and closing lines."""
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
    """Transform prose while retaining fenced and inline code byte for byte."""
    prefix = "\x00ZJU-CODE\x00"
    while prefix in text:
        prefix += "\x00"
    out = []
    prose = []

    def flush() -> None:
        if not prose:
            return
        kept = []

        def protect(match):
            token = prefix + str(len(kept)) + "\x00"
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
