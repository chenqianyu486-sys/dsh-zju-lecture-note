# -*- coding: utf-8 -*-
"""Download projected-slide screenshots and assemble them into a PDF.

The classroom ``search-ppt`` API returns **screenshots**, not a text layer.
This module turns the URLs into local files and one PDF so the slides can be
opened, archived, or read by a vision-capable model. Everything is standard
library: JPEGs are embedded verbatim (DCTDecode), PNGs are decoded and
inflated (FlateDecode), and no image is re-encoded.

Security boundaries:

* only ``https://*.zju.edu.cn`` image URLs are fetched;
* plain ``http`` is upgraded to HTTPS for ZJU hosts and refused otherwise;
* the login Cookie is only sent to ZJU hosts (never to arbitrary URLs the
  API may return), and ``Authorization`` is never sent to image hosts;
* image bytes are validated by magic number before anything is written.
"""

import hashlib
import os
import urllib.error
import urllib.parse
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .client import (
    BASE_URL,
    USER_AGENT,
    _fetch_bytes,
    extract_classroom_token,
    is_zju_host,
    secure_zju_url,
)
from .security import sanitize_cookie_header

MAX_SLIDES = 2000
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
DOWNLOAD_WORKERS = 6


class SlideError(Exception):
    """Raised when a screenshot cannot be downloaded or rendered."""


def _record(diagnostics: Optional[List[str]], message: str) -> None:
    if diagnostics is not None:
        diagnostics.append(message)


def _safe_image_url(url: str) -> Optional[str]:
    """Return the HTTPS ZJU URL to fetch, or ``None`` when it is unsafe."""
    value = secure_zju_url(url)
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https":
        return None
    if parsed.username or parsed.password:
        return None
    if not is_zju_host(parsed.hostname):
        return None
    return value


def _image_kind(data: bytes) -> Tuple[Optional[str], str]:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg", ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", ".png"
    return None, ""


def _download_one(
    index: int,
    slide: Dict[str, Any],
    cookie: str,
    sub_id: str,
    target_dir: str,
    timeout: int,
    token: Optional[str],
) -> Tuple[int, Optional[Dict[str, Any]], Optional[str]]:
    url = str(slide.get("image_url") or "").strip()
    if not url:
        return index, None, "该页没有截图地址"
    safe_url = _safe_image_url(url)
    if safe_url is None:
        return index, None, "截图地址不是 HTTPS 浙大主机，已拒绝下载"

    host = (urllib.parse.urlparse(safe_url).hostname or "").lower()
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"{BASE_URL}/livingroom?sub_id={sub_id}",
    }
    if is_zju_host(host) and cookie:
        headers["Cookie"] = cookie

    try:
        try:
            data = _fetch_bytes(
                safe_url,
                headers,
                timeout,
                attempts=3,
                max_bytes=MAX_IMAGE_BYTES,
                allow_cross_host_redirect=True,
            )
        except urllib.error.HTTPError as error:
            if error.code in (401, 403) and token:
                retry_headers = dict(headers)
                retry_headers["Authorization"] = f"Bearer {token}"
                data = _fetch_bytes(
                    safe_url,
                    retry_headers,
                    timeout,
                    attempts=2,
                    max_bytes=MAX_IMAGE_BYTES,
                    allow_cross_host_redirect=True,
                )
            else:
                raise
    except urllib.error.HTTPError as error:
        return index, None, f"HTTP {error.code}"
    except Exception as error:  # noqa: BLE001 - one bad image must not abort the deck
        return index, None, str(error).splitlines()[0][:200]

    kind, extension = _image_kind(data)
    if kind is None:
        return index, None, "响应不是 JPEG/PNG（可能是登录失效页或错误页）"

    path = os.path.join(target_dir, f"slide-{index + 1:04d}{extension}")
    part = path + ".part"
    try:
        with open(part, "wb") as handle:
            handle.write(data)
        os.replace(part, path)
    except OSError as error:
        try:
            os.unlink(part)
        except OSError:
            pass
        return index, None, f"截图写入失败: {error}"

    return index, {
        "path": path,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "kind": kind,
    }, None


def download_slides(
    slides: Iterable[Dict[str, Any]],
    target_dir: str,
    cookie: str = "",
    sub_id: str = "",
    timeout: int = 30,
    workers: int = DOWNLOAD_WORKERS,
    dedup: bool = True,
    diagnostics: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Download every slide screenshot into ``target_dir``.

    Returns a summary with the slides kept for the PDF. Each successfully
    downloaded slide gains ``local_path`` / ``local_bytes`` / ``sha256``.
    Consecutive byte-identical screenshots are collapsed for the PDF (idle
    projection), while every downloaded file stays on disk.
    """
    slides = list(slides)
    os.makedirs(target_dir, exist_ok=True)
    if cookie:
        try:
            cookie = sanitize_cookie_header(cookie)
        except ValueError as error:
            _record(diagnostics, f"Cookie 头未通过校验：{error}")
            cookie = ""
    token = extract_classroom_token(cookie)

    indexed = [
        (index, slide)
        for index, slide in enumerate(slides)
        if isinstance(slide, dict) and slide.get("image_url")
    ]
    skipped = len(slides) - len(indexed)
    if len(indexed) > MAX_SLIDES:
        _record(diagnostics, f"截图数量超过 {MAX_SLIDES} 张上限，只下载前 {MAX_SLIDES} 张")
        indexed = indexed[:MAX_SLIDES]

    results: List[Tuple[int, Optional[Dict[str, Any]], Optional[str]]] = []
    pool_size = max(1, min(int(workers or DOWNLOAD_WORKERS), 8))
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        futures = [
            pool.submit(
                _download_one,
                index,
                slide,
                cookie,
                sub_id,
                target_dir,
                timeout,
                token,
            )
            for index, slide in indexed
        ]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item[0])

    failures: List[str] = []
    downloaded = 0
    total_bytes = 0
    for index, info, error in results:
        slide = slides[index]
        if error:
            failures.append(error)
            continue
        if info is None:
            continue
        slide["local_path"] = info["path"]
        slide["local_bytes"] = info["bytes"]
        slide["sha256"] = info["sha256"]
        downloaded += 1
        total_bytes += int(info["bytes"])

    for error in failures[:5]:
        _record(diagnostics, f"截图下载失败：{error}")
    if len(failures) > 5:
        _record(diagnostics, f"另有 {len(failures) - 5} 张截图下载失败")
    if skipped:
        _record(diagnostics, f"{skipped} 页没有截图地址（只有文字或空记录）")
    if total_bytes > MAX_TOTAL_BYTES:
        _record(
            diagnostics,
            f"截图总大小 {total_bytes // (1024 * 1024)} MiB 超过 "
            f"{MAX_TOTAL_BYTES // (1024 * 1024)} MiB，PDF 可能很大",
        )

    kept: List[Dict[str, Any]] = []
    duplicates = 0
    previous_hash = None
    for _index, slide in indexed:
        if not slide.get("local_path"):
            continue
        digest = slide.get("sha256")
        if dedup and digest and digest == previous_hash:
            duplicates += 1
            continue
        kept.append(slide)
        previous_hash = digest

    if downloaded == 0:
        _record(diagnostics, "没有成功下载任何截图")

    return {
        "downloaded": downloaded,
        "failed": len(failures),
        "skipped": skipped,
        "duplicates": duplicates,
        "images_dir": target_dir,
        "pages": kept,
        "total_bytes": total_bytes,
    }


# --------------------------------------------------------------------------- PDF

_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def _jpeg_info(data: bytes) -> Tuple[int, int, int]:
    """Return ``(width, height, components)`` from a JPEG header."""
    if not data.startswith(b"\xff\xd8"):
        raise SlideError("不是 JPEG")
    pos = 2
    while pos + 1 < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if pos + 2 > len(data):
            break
        length = int.from_bytes(data[pos: pos + 2], "big")
        if length < 2 or pos + length > len(data):
            break
        if marker in _SOF_MARKERS:
            if length < 8:
                break
            height = int.from_bytes(data[pos + 3: pos + 5], "big")
            width = int.from_bytes(data[pos + 5: pos + 7], "big")
            components = data[pos + 7]
            if not width or not height:
                break
            return width, height, components
        pos += length
    raise SlideError("无法解析 JPEG 尺寸")


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_up_left = abs(estimate - up_left)
    if distance_left <= distance_up and distance_left <= distance_up_left:
        return left
    if distance_up <= distance_up_left:
        return up
    return up_left


def _unfilter(filter_type: int, line: bytearray, previous: bytearray, bpp: int) -> None:
    """Undo one PNG scanline filter in place."""
    if filter_type == 0:
        return
    if filter_type == 1:
        for index in range(bpp, len(line)):
            line[index] = (line[index] + line[index - bpp]) & 0xFF
        return
    if filter_type == 2:
        for index in range(len(line)):
            line[index] = (line[index] + previous[index]) & 0xFF
        return
    if filter_type == 3:
        for index in range(len(line)):
            left = line[index - bpp] if index >= bpp else 0
            line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        return
    if filter_type == 4:
        for index in range(len(line)):
            left = line[index - bpp] if index >= bpp else 0
            up = previous[index]
            up_left = previous[index - bpp] if index >= bpp else 0
            line[index] = (line[index] + _paeth(left, up, up_left)) & 0xFF
        return
    raise SlideError(f"不支持的 PNG 行过滤类型: {filter_type}")


def _png_decode(data: bytes) -> Tuple[int, int, bytes, int]:
    """Decode an 8-bit, non-interlaced PNG into raw gray/RGB samples."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SlideError("不是 PNG")
    pos = 8
    idat = bytearray()
    width = height = bit_depth = color_type = interlace = None
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos: pos + 4], "big")
        chunk_type = data[pos + 4: pos + 8]
        chunk = data[pos + 8: pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"IHDR":
            if len(chunk) < 13:
                raise SlideError("PNG IHDR 不完整")
            width = int.from_bytes(chunk[0:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            bit_depth = chunk[8]
            color_type = chunk[9]
            interlace = chunk[12]
        elif chunk_type == b"IDAT":
            idat.extend(chunk)
        elif chunk_type == b"IEND":
            break
    if not width or not height:
        raise SlideError("PNG 缺少尺寸")
    if bit_depth != 8 or interlace != 0:
        raise SlideError("PDF 只支持 8 位非隔行 PNG")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type or -1)
    if channels is None:
        raise SlideError("PDF 不支持该 PNG 色彩类型")
    if width * height * channels > 256 * 1024 * 1024:
        raise SlideError("PNG 解码后超过 256 MiB 上限")

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as error:
        raise SlideError(f"PNG 解压失败: {error}") from error

    stride = width * channels
    previous = bytearray(stride)
    samples = bytearray()
    cursor = 0
    for _ in range(height):
        if cursor >= len(raw):
            raise SlideError("PNG 像素数据不完整")
        filter_type = raw[cursor]
        cursor += 1
        line = bytearray(raw[cursor: cursor + stride])
        cursor += stride
        if len(line) != stride:
            raise SlideError("PNG 像素数据不完整")
        _unfilter(filter_type, line, previous, channels)
        previous = line
        if channels == 2:
            samples.extend(line[0::2])
        elif channels == 4:
            samples.extend(byte for index, byte in enumerate(line) if index % 4 != 3)
        else:
            samples.extend(line)

    out_channels = 1 if channels in (1, 2) else 3
    return width, height, bytes(samples), out_channels


def _load_image(path: str) -> Dict[str, Any]:
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_IMAGE_BYTES + 1)
    except OSError as error:
        raise SlideError(f"读取截图失败: {error}") from error
    if len(data) > MAX_IMAGE_BYTES:
        raise SlideError("截图超过单张大小上限")
    if data.startswith(b"\xff\xd8\xff"):
        width, height, components = _jpeg_info(data)
        color_space = {1: "/DeviceGray", 3: "/DeviceRGB", 4: "/DeviceCMYK"}.get(components)
        if color_space is None:
            raise SlideError(f"不支持的 JPEG 通道数: {components}")
        return {
            "width": width,
            "height": height,
            "color_space": color_space,
            "filter": "/DCTDecode",
            "data": data,
        }
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height, samples, channels = _png_decode(data)
        return {
            "width": width,
            "height": height,
            "color_space": "/DeviceGray" if channels == 1 else "/DeviceRGB",
            "filter": "/FlateDecode",
            "data": zlib.compress(samples, 6),
        }
    raise SlideError("PDF 只支持 JPEG / PNG 截图")


def _page_size(width: int, height: int) -> Tuple[float, float]:
    scale = min(1.0, 2000.0 / max(width, height))
    return max(1.0, width * scale), max(1.0, height * scale)


def _write_pdf(images: List[Dict[str, Any]], path: str) -> None:
    part = path + ".part"
    try:
        with open(part, "wb") as handle:
            count = len(images)
            total_objects = 2 + count * 3
            offsets = [0] * (total_objects + 1)
            handle.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

            def begin(number: int) -> None:
                offsets[number] = handle.tell()
                handle.write(f"{number} 0 obj\n".encode("ascii"))

            def end() -> None:
                handle.write(b"\nendobj\n")

            begin(1)
            handle.write(b"<< /Type /Catalog /Pages 2 0 R >>")
            end()

            begin(2)
            kids = " ".join(f"{3 + index * 3} 0 R" for index in range(count))
            handle.write(
                f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode("ascii")
            )
            end()

            for index, image in enumerate(images):
                page_number = 3 + index * 3
                content_number = page_number + 1
                image_number = page_number + 2
                width, height = _page_size(image["width"], image["height"])

                begin(page_number)
                handle.write(
                    (
                        f"<< /Type /Page /Parent 2 0 R "
                        f"/MediaBox [0 0 {width:.4f} {height:.4f}] "
                        f"/Resources << /XObject << /Im0 {image_number} 0 R >> >> "
                        f"/Contents {content_number} 0 R >>"
                    ).encode("ascii")
                )
                end()

                stream = f"q {width:.4f} 0 0 {height:.4f} 0 0 cm /Im0 Do Q\n".encode(
                    "ascii"
                )
                begin(content_number)
                handle.write(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii"))
                handle.write(stream)
                handle.write(b"endstream")
                end()

                begin(image_number)
                extra = (
                    b" /Decode [1 0 1 0 1 0 1 0]"
                    if image["color_space"] == "/DeviceCMYK"
                    else b""
                )
                handle.write(
                    (
                        f"<< /Type /XObject /Subtype /Image "
                        f"/Width {image['width']} /Height {image['height']} "
                        f"/ColorSpace {image['color_space']} /BitsPerComponent 8 "
                        f"/Filter {image['filter']} /Length {len(image['data'])}"
                    ).encode("ascii")
                )
                handle.write(extra)
                handle.write(b" >>\nstream\n")
                handle.write(image["data"])
                handle.write(b"\nendstream")
                end()

            xref_offset = handle.tell()
            handle.write(f"xref\n0 {total_objects + 1}\n".encode("ascii"))
            handle.write(b"0000000000 65535 f \n")
            for number in range(1, total_objects + 1):
                handle.write(f"{offsets[number]:010d} 00000 n \n".encode("ascii"))
            handle.write(
                (
                    f"trailer\n<< /Size {total_objects + 1} /Root 1 0 R >>\n"
                    f"startxref\n{xref_offset}\n%%EOF\n"
                ).encode("ascii")
            )
        os.replace(part, path)
    except Exception:
        try:
            os.unlink(part)
        except OSError:
            pass
        raise


def build_slides_pdf(
    pages: Iterable[Any],
    output_path: str,
    diagnostics: Optional[List[str]] = None,
) -> Optional[str]:
    """Write downloaded screenshots into one PDF; return its path or ``None``.

    ``pages`` may be slide dicts (with ``local_path``) or plain paths. A page
    that cannot be decoded is skipped with a diagnostic instead of failing the
    whole deck.
    """
    paths: List[str] = []
    for page in pages:
        if isinstance(page, dict):
            value = page.get("local_path")
        else:
            value = page
        if isinstance(value, str) and value:
            paths.append(value)

    images: List[Dict[str, Any]] = []
    failures = 0
    for path in paths:
        try:
            images.append(_load_image(path))
        except SlideError as error:
            failures += 1
            if failures <= 5:
                _record(diagnostics, f"跳过无法写入 PDF 的截图 {os.path.basename(path)}：{error}")
    if failures > 5:
        _record(diagnostics, f"另有 {failures - 5} 张截图无法写入 PDF")
    if not images:
        _record(diagnostics, "没有可写入 PDF 的 JPEG/PNG 截图")
        return None

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    try:
        _write_pdf(images, output_path)
    except Exception as error:  # noqa: BLE001 - report as a tool-level failure
        _record(diagnostics, f"写入 PDF 失败: {error}")
        return None
    return output_path
