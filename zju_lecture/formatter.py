# -*- coding: utf-8 -*-
"""
Transcript and courseware formatters.
Formats timestamps, groups text by minutes, slices by time window,
and prepares structured text for agent consumption.
"""

from typing import Any, Dict, List, Optional, Tuple


def format_timestamp(seconds: int, include_hours: bool = True) -> str:
    """Format seconds into HH:MM:SS or MM:SS string."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if include_hours or h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def filter_segments(
    segments: List[Dict[str, Any]],
    start_sec: Optional[int] = None,
    end_sec: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Filter transcript segments by timestamp window."""
    result = []
    for s in segments:
        sec = s["begin_sec"]
        if start_sec is not None and sec < start_sec:
            continue
        if end_sec is not None and sec > end_sec:
            continue
        result.append(s)
    return result


def build_transcript_views(
    segments: List[Dict[str, Any]]
) -> Tuple[str, str, Dict[int, List[str]]]:
    """Build two views of transcript:
    1. per_seg_text: Each line has [HH:MM:SS] timestamp
    2. per_min_text: Aggregated by minute [HH:MM]
    3. minutes_map: {minute_index: [text_items]}
    """
    if not segments:
        return "", "", {}

    per_seg_lines = []
    minutes_map: Dict[int, List[str]] = {}

    for s in segments:
        sec = s["begin_sec"]
        text = s["text"]
        per_seg_lines.append(f"[{format_timestamp(sec)}] {text}")
        m_idx = sec // 60
        minutes_map.setdefault(m_idx, []).append(text)

    per_min_lines = []
    for m in sorted(minutes_map.keys()):
        h = m // 60
        mn = m % 60
        per_min_lines.append(f"[{h:02d}:{mn:02d}] " + "".join(minutes_map[m]))

    per_seg_text = "\n".join(per_seg_lines)
    per_min_text = "\n".join(per_min_lines)
    return per_seg_text, per_min_text, minutes_map


def format_minute_span(start_min: int, end_min: int) -> str:
    """Format a minute range as ``HH:MM-HH:MM``.

    ``end_min`` is inclusive: the span ends at the *end* of that minute, so
    minute 59 ends at 01:00, not 00:00.
    """
    end_exclusive = end_min + 1
    return (
        f"{start_min // 60:02d}:{start_min % 60:02d}-"
        f"{end_exclusive // 60:02d}:{end_exclusive % 60:02d}"
    )


def chunk_transcript(
    minutes_map: Dict[int, List[str]],
    max_chars: int = 11000
) -> List[Dict[str, Any]]:
    """Chunk aggregated transcript by minutes, ensuring each chunk does not exceed max_chars.
    Returns:
        List of dicts:
        [{
            "chunk_index": int,
            "start_min": int,
            "end_min": int,
            "time_span": "00:00–00:45",
            "text": str,
            "char_count": int
        }]
    """
    chunks: List[Dict[str, Any]] = []
    cur_items: List[Tuple[int, str]] = []
    cur_len = 0
    cur_start_min: Optional[int] = None

    sorted_minutes = sorted(minutes_map.keys())
    for m in sorted_minutes:
        h = m // 60
        mn = m % 60
        line = f"[{h:02d}:{mn:02d}] " + "".join(minutes_map[m])
        line_len = len(line)

        if cur_items and (cur_len + line_len > max_chars):
            end_m = cur_items[-1][0]
            start_m = cur_start_min if cur_start_min is not None else 0
            span_str = format_minute_span(start_m, end_m)
            text_body = "\n".join(x[1] for x in cur_items)
            chunks.append({
                "chunk_index": len(chunks) + 1,
                "start_min": start_m,
                "end_min": end_m,
                "time_span": span_str,
                "text": text_body,
                "char_count": len(text_body),
            })
            cur_items = []
            cur_start_min = None
            cur_len = 0

        if cur_start_min is None:
            cur_start_min = m
        cur_items.append((m, line))
        cur_len += line_len + 1

    if cur_items:
        end_m = cur_items[-1][0]
        start_m = cur_start_min if cur_start_min is not None else 0
        span_str = format_minute_span(start_m, end_m)
        text_body = "\n".join(x[1] for x in cur_items)
        chunks.append({
            "chunk_index": len(chunks) + 1,
            "start_min": start_m,
            "end_min": end_m,
            "time_span": span_str,
            "text": text_body,
            "char_count": len(text_body),
        })

    return chunks


def format_slides_as_markdown(slides_list: Optional[List[Dict[str, Any]]]) -> str:
    """Format raw slide json list into clean markdown outline."""
    if not slides_list:
        return ""

    lines = ["### 课堂投影 PPT 文字记录"]
    for idx, slide in enumerate(slides_list, start=1):
        # Examine slide dict fields
        content = slide.get("content") or slide.get("text") or slide.get("ocr_content") or ""
        time_point = slide.get("time") or slide.get("time_point") or slide.get("sec")
        ts_str = f" [{format_timestamp(int(time_point))}]" if time_point is not None else ""
        title = slide.get("title") or f"幻灯片 {idx}"
        lines.append(f"#### {title}{ts_str}")
        if content.strip():
            lines.append(content.strip())
        lines.append("")
    return "\n".join(lines)
