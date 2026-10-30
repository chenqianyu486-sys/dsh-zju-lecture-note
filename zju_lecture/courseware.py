# -*- coding: utf-8 -*-
"""
Courseware text extraction without heavy dependencies.
Extracts text from .pptx, .docx, .txt, .md, and optionally .pdf.
"""

import os
import re
import zipfile
from typing import Optional


class CoursewareError(Exception):
    pass


def extract_courseware_text(path: str, max_chars: Optional[int] = None) -> str:
    """Extract plain text from local courseware files.
    
    Supported formats:
    - .pptx: Extracted from XML slide contents
    - .docx: Extracted from XML document contents
    - .txt, .md: Plain text with encoding fallbacks
    - .pdf: Extracted via pypdf or PyPDF2 if installed, or basic regex fallback
    """
    if not os.path.isfile(path):
        raise CoursewareError(f"课件文件不存在: {path}")

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


def _extract_docx(path: str) -> str:
    """Extract text from document.xml inside DOCX zip package."""
    try:
        with zipfile.ZipFile(path, "r") as z:
            xml_content = z.read("word/document.xml").decode("utf-8", "ignore")
            # Replace paragraph tags with newlines
            xml_content = re.sub(r"</w:p>", "\n", xml_content)
            texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml_content)
            # Normalize whitespace
            return "".join(texts).strip()
    except Exception as e:
        raise CoursewareError(f"读取 DOCX 课件失败: {e}")


def _extract_pdf(path: str) -> str:
    """Extract text from PDF using pypdf if available, or fall back to basic stream extraction."""
    try:
        import pypdf
        reader = pypdf.PdfReader(path)
        pages_text = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages_text)
    except ImportError:
        pass

    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(path)
        pages_text = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages_text)
    except ImportError:
        pass

    # Basic fallback: read binary, search for text chunks (limited but zero-dep)
    try:
        with open(path, "rb") as f:
            content = f.read()
        strings = re.findall(rb"\(([\w\s\d,.\-+=/]{3,})\)Tj", content)
        if strings:
            return " ".join(s.decode("latin-1", "ignore") for s in strings)
    except Exception:
        pass

    raise CoursewareError(
        "PDF 解析需要可选依赖 'pypdf'。请在终端执行: pip install pypdf"
    )
