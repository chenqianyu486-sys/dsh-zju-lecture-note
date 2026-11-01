# -*- coding: utf-8 -*-
"""
Courseware text extraction without heavy dependencies.
Extracts text from .pptx, .docx, .txt, .md, and optionally .pdf.
"""

import html
import importlib
import os
import re
import sys
import zipfile
from typing import Optional

from .security import COURSEWARE_EXTENSIONS, LocalFileError, guard_local_file


class CoursewareError(Exception):
    pass


def extract_courseware_text(path: str, max_chars: Optional[int] = None) -> str:
    """Extract plain text from local courseware files.

    Supported formats:
    - .pptx: Extracted from XML slide contents
    - .docx: Extracted from XML document contents
    - .txt, .md: Plain text with encoding fallbacks
    - .pdf: Extracted via pypdf or PyPDF2 if installed, or basic regex fallback

    The path is validated first: only courseware extensions are accepted and
    credential stores / browser databases / key material are refused, so a
    model cannot turn this tool into a generic local-file reader.
    """
    try:
        path = guard_local_file(path, COURSEWARE_EXTENSIONS, kind="课件文件")
    except LocalFileError as exc:
        raise CoursewareError(str(exc)) from exc

    ext = os.path.splitext(path)[1].lower()

    if ext in (".txt", ".md", ".csv", ".json"):
        text = _read_text_file(path)
    elif ext == ".pptx":
        text = _extract_pptx(path)
    elif ext == ".docx":
        text = _extract_docx(path)
    elif ext == ".pdf":
        text = _extract_pdf(path)
    else:
        raise CoursewareError(
            f"暂不支持的课件格式 '{ext}'。目前支持: .pptx, .docx, .txt, .md, .pdf"
        )

    if max_chars and len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[... 课件内容过长，已截断前 {max_chars} 字符 ...]"

    return text.strip()


def _read_text_file(path: str) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _extract_pptx(path: str) -> str:
    """Extract text from slides inside PPTX zip package."""
    try:
        with zipfile.ZipFile(path, "r") as z:
            slide_names = [
                n for n in z.namelist()
                if re.match(r"^ppt/slides/slide\d+\.xml$", n)
            ]
            # Sort slides by numeric slide index
            slide_names.sort(
                key=lambda n: int(re.search(r"(\d+)", n).group(1))
            )

            parts = []
            for idx, name in enumerate(slide_names, start=1):
                xml_content = z.read(name).decode("utf-8", "ignore")
                texts = re.findall(r"<a:t>([^<]*)</a:t>", xml_content)
                cleaned = " ".join(t.strip() for t in texts if t.strip())
                if cleaned:
                    parts.append(f"[幻灯片 {idx}]\n{cleaned}")

            return "\n\n".join(parts)
    except Exception as e:
        raise CoursewareError(f"读取 PPTX 课件失败: {e}")


_DOCX_TOKEN_RE = re.compile(
    r"<w:t(?:\s[^>]*)?>(?P<text>.*?)</w:t>"
    r"|<w:br(?:\s[^>]*)?/?>"
    r"|<w:tab(?:\s[^>]*)?/?>"
    r"|</w:p>",
    re.DOTALL,
)


def _extract_docx(path: str) -> str:
    """Extract text from ``word/document.xml``, keeping paragraph structure.

    A DOCX paragraph is ``<w:p>``; the text inside it lives in ``<w:t>``.
    Replacing ``</w:p>`` with a newline *before* joining ``<w:t>`` fragments
    drops every newline again, so the old implementation collapsed the whole
    document into a single line. Walking the token stream keeps paragraphs,
    tabs and explicit line breaks.
    """
    try:
        with zipfile.ZipFile(path, "r") as z:
            xml_content = z.read("word/document.xml").decode("utf-8", "ignore")
    except Exception as e:
        raise CoursewareError(f"读取 DOCX 课件失败: {e}")

    out = []
    for match in _DOCX_TOKEN_RE.finditer(xml_content):
        text = match.group("text")
        if text is not None:
            out.append(html.unescape(text))
        elif match.group(0).startswith("</w:p"):
            out.append("\n")
        elif match.group(0).startswith("<w:br"):
            out.append("\n")
        elif match.group(0).startswith("<w:tab"):
            out.append("\t")

    text = "".join(out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_pdf(path: str) -> str:
    """Extract text from a PDF, explaining every failed attempt.

    ``pypdf`` is an optional dependency and dsh ships its own Python, so a
    bare ``pip install pypdf`` is ambiguous: it may have been installed into a
    *different* interpreter. Every failure therefore records the library, the
    exception type and the absolute path of the interpreter that was used.
    """
    attempts = []
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            attempts.append(f"{module_name}: 未安装")
            continue
        try:
            reader = module.PdfReader(path)
            pages_text = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages_text)
        except Exception as exc:  # noqa: BLE001 - report, do not crash
            attempts.append(f"{module_name}: {type(exc).__name__}: {exc}")

    # Basic fallback: read binary, search for plain text show operators.
    try:
        with open(path, "rb") as f:
            content = f.read()
        strings = re.findall(rb"\(([\w\s\d,.\-+=/]{3,})\)Tj", content)
        if strings:
            return " ".join(s.decode("latin-1", "ignore") for s in strings)
        attempts.append("内置兜底解析: 未找到可读文本层")
    except Exception as exc:  # noqa: BLE001 - report, do not crash
        attempts.append(f"内置兜底解析: {type(exc).__name__}: {exc}")

    detail = "；".join(attempts) or "无可用 PDF 解析器"
    raise CoursewareError(
        "无法解析 PDF 课件。\n"
        f"当前 Python 解释器: {sys.executable}\n"
        f"尝试结果: {detail}\n"
        "如需完整 PDF 支持，请给上面这个解释器安装 pypdf："
        f'"{sys.executable}" -m pip install pypdf'
    )
