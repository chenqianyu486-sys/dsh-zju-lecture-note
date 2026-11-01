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


# ------------------------------------------------------------ ASR quality signal

#: Spoken-language filler that the ASR happily transcribes but a lecture note
#: must drop. Longer tokens come first so "这个" wins over a bare "这".
#: "我们" is deliberately absent (every lecture says it and it is not noise),
#: and so is "哈" (it would fire on 哈密顿 / 哈密尔顿).
_FILLER_TOKENS = (
    "是不是", "对不对", "知道吧", "对吧", "这个", "那个", "就是", "然后",
    "那么", "嗯", "啊", "呃", "哦", "诶", "呀", "嘛",
)

#: A segment at or below this length was probably cut mid-sentence.
_FRAGMENT_CHARS = 8

#: Chinese ASR of a lecture averages well above this; going below it means the
#: recognizer was producing fragments rather than sentences.
_LOW_AVG_CHARS = 14.0

_RELIABILITY_TEXT = {"high": "高", "medium": "中", "low": "低"}

_HINT_TEXT = {
    "high": "ASR 文本可直接使用；公式与专业术语仍按数学规范书写。",
    "medium": (
        "ASR 文本有较多口语碎片或碎句，术语与数字可能听错；"
        "涉及公式推导、参数、结论的地方请按数学规范复算后再写进讲义。"
    ),
    "low": (
        "ASR 质量偏低：大量口头禅与碎句，关键术语极可能被识别成近音错字。"
        "**不要照字面直译**：所有表达式按数学规范重新推导校核，"
        "无法还原的地方在正文用 ⚠ 标注并给出复算结论，"
        "并在讲义开头写明 ASR 限制与需要复核的时间点。"
    ),
}


def transcript_quality(
    segments: List[Dict[str, Any]],
    max_fillers: int = 3,
) -> Dict[str, Any]:
    """Return a compact, honest ASR-quality signal for one transcript.

    The recognizer never says how far it can be trusted, so a note built from a
    bad transcript *looks* exactly like one built from a good transcript. This
    turns three cheap, checkable symptoms into a level the agent can act on:

    * ``noise_ratio`` — share of characters that are spoken filler
      ("嗯"、"这个"、"然后" …);
    * ``fragment_ratio`` — share of segments at or below ``_FRAGMENT_CHARS``
      (the recognizer cut a sentence instead of finishing it);
    * ``avg_chars`` — average segment length.

    It is a heuristic, not a verdict: it says "worth double-checking", not
    "wrong". ``hint`` phrases the consequence for note writing.
    """
    if not segments:
        return {
            "reliability": "unknown",
            "noise_ratio": 0.0,
            "fragment_ratio": 0.0,
            "avg_chars": 0.0,
            "top_fillers": [],
            "hint": "没有字幕内容，无法评估 ASR 质量。",
        }

    texts = [str(segment.get("text") or "") for segment in segments]
    total_chars = sum(len(text) for text in texts) or 1
    segments_count = len(texts) or 1

    filler_counter: Dict[str, int] = {}
    filler_chars = 0
    for text in texts:
        for token in _FILLER_TOKENS:
            count = text.count(token)
            if not count:
                continue
            filler_counter[token] = filler_counter.get(token, 0) + count
            filler_chars += count * len(token)

    noise_ratio = filler_chars / total_chars
    fragment_ratio = sum(1 for text in texts if 0 < len(text) <= _FRAGMENT_CHARS) / segments_count
    avg_chars = total_chars / segments_count

    if noise_ratio >= 0.10 or fragment_ratio >= 0.45:
        reliability = "low"
    elif noise_ratio >= 0.04 or fragment_ratio >= 0.28 or avg_chars < _LOW_AVG_CHARS:
        reliability = "medium"
    else:
        reliability = "high"

    top_fillers = [
        {"token": token, "count": count}
        for token, count in sorted(
            filler_counter.items(), key=lambda item: (-item[1], item[0])
        )[:max_fillers]
        if count > 0
    ]

    return {
        "reliability": reliability,
        "noise_ratio": round(noise_ratio, 3),
        "fragment_ratio": round(fragment_ratio, 3),
        "avg_chars": round(avg_chars, 1),
        "top_fillers": top_fillers,
        "hint": _HINT_TEXT.get(reliability, ""),
    }


def format_quality_line(quality: Dict[str, Any]) -> str:
    """One-line rendering of :func:`transcript_quality` for a text view."""
    if not quality:
        return ""
    level = str(quality.get("reliability") or "unknown")
    label = _RELIABILITY_TEXT.get(level, level)
    fillers = "、".join(
        f"{item.get('token')}×{item.get('count')}" for item in quality.get("top_fillers") or []
    )
    parts = [
        f"噪声比 {float(quality.get('noise_ratio') or 0) * 100:.1f}%",
        f"碎句比 {float(quality.get('fragment_ratio') or 0) * 100:.0f}%",
        f"平均句长 {float(quality.get('avg_chars') or 0):.0f} 字",
    ]
    if fillers:
        parts.append(f"高频口头禅 {fillers}")
    line = f"ASR 可靠度: {label}（{' | '.join(parts)}）"
    hint = str(quality.get("hint") or "").strip()
    if hint and level in ("low", "medium"):
        line += f"\n注意: {hint}"
    return line


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
