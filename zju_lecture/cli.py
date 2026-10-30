# -*- coding: utf-8 -*-
"""
Command-line interface for ZJU Lecture tools.
"""

import argparse
import json
import os
import sys

from .client import (
    BASE_URL,
    ZJUAPIError,
    fetch_slides,
    fetch_transcript,
    fetch_video_url,
    parse_lecture_url,
)
from .cookies import get_edge_cookie
from .courseware import CoursewareError, extract_courseware_text
from .formatter import (
    build_transcript_views,
    chunk_transcript,
    filter_segments,
    format_slides_as_markdown,
    format_timestamp,
)
from .security import describe_cookie, sanitize_cookie_header


def _read_cookie_file(path: str) -> str:
    """Read a cookie header from a local file (never printed)."""
    with open(os.path.expanduser(path), "r", encoding="utf-8") as handle:
        raw = handle.readline().strip()
    return sanitize_cookie_header(raw)


def _load_cookie(explicit: str = "", cookie_file: str = "") -> str:
    """Resolve a cookie: explicit arg > file > ZJU_COOKIE env > local Edge."""
    if explicit:
        print(
            "[zju-lecture] 警告: --cookie 会出现在进程列表中；建议改用 --cookie-file 或 ZJU_COOKIE。",
            file=sys.stderr,
        )
        return sanitize_cookie_header(explicit)
    if cookie_file:
        return _read_cookie_file(cookie_file)
    env_cookie = os.environ.get("ZJU_COOKIE", "").strip()
    if env_cookie:
        return sanitize_cookie_header(env_cookie)
    return get_edge_cookie() or ""


def _run_mcp_server() -> None:
    """Start the stdio MCP server.

    ``mcp_server.py`` lives next to the ``zju_lecture`` package, so it is
    loaded by path instead of a relative import (which cannot escape the
    package when the CLI is started with ``python -m zju_lecture.cli``).
    """
    import importlib.util

    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    module_path = os.path.join(parent_dir, "mcp_server.py")
    if not os.path.isfile(module_path):
        raise RuntimeError(f"找不到 MCP 服务器脚本: {module_path}")
    spec = importlib.util.spec_from_file_location("zju_lecture_mcp_server", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 MCP 服务器脚本: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


def main():
    parser = argparse.ArgumentParser(
        description="浙大智云课堂 (ZJU Classroom) Agent 工具集与命令行 CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # Command: parse
    p_parse = subparsers.add_parser("parse", help="解析课程回放链接")
    p_parse.add_argument("url", help="回放 URL 或 sub_id")

    # Command: fetch
    p_fetch = subparsers.add_parser("fetch", help="抓取课程语音识别字幕（公开免登录）")
    p_fetch.add_argument("url", help="回放 URL 或 sub_id")
    p_fetch.add_argument(
        "--format",
        choices=["min", "seg", "chunk", "json"],
        default="min",
        help="输出格式: min (按分钟合并), seg (逐段), chunk (分块), json (原始)",
    )
    p_fetch.add_argument("--start", type=int, help="起始分钟")
    p_fetch.add_argument("--end", type=int, help="结束分钟")
    p_fetch.add_argument("--out", "-o", help="输出文件路径")

    # Command: slides
    p_slides = subparsers.add_parser("slides", help="抓取课堂 PPT 文字层（需 Cookie）")
    p_slides.add_argument("url", help="回放 URL 或 sub_id")
    p_slides.add_argument(
        "--cookie-file",
        help="从文件读取 Cookie（推荐；避免出现在进程列表与 shell 历史里）",
    )
    p_slides.add_argument(
        "--cookie",
        help="直接传 Cookie 字符串（会出现在进程列表，已不推荐；留空则依次尝试 "
             "--cookie-file / ZJU_COOKIE / 本机 Edge）",
    )
    p_slides.add_argument("--out", "-o", help="输出 Markdown 路径")

    # Command: courseware
    p_cw = subparsers.add_parser("courseware", help="从本地课件文件提取文字 (pptx/docx/txt/md/pdf)")
    p_cw.add_argument("file", help="课件文件路径")
    p_cw.add_argument("--max-chars", type=int, default=10000, help="最多提取字符数")

    # Command: cookie
    p_cookie = subparsers.add_parser("cookie", help="从本机 Edge 读取智云课堂 Cookie")
    p_cookie.add_argument(
        "--reveal",
        action="store_true",
        help="回显 Cookie 明文（默认只显示名称与长度；明文会进入终端历史，谨慎使用）",
    )

    # Command: mcp
    p_mcp = subparsers.add_parser("mcp", help="启动 MCP stdio 服务")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "parse":
            res = parse_lecture_url(args.url)
            print(json.dumps(res, ensure_ascii=False, indent=2))

        elif args.command == "fetch":
            parsed = parse_lecture_url(args.url)
            sub_id = parsed["sub_id"]
            tenant = parsed.get("tenant_code", "112")
            segs = fetch_transcript(sub_id, tenant)

            start_sec = args.start * 60 if args.start is not None else None
            end_sec = (args.end * 60 + 59) if args.end is not None else None
            if start_sec is not None or end_sec is not None:
                segs = filter_segments(segs, start_sec, end_sec)

            per_seg, per_min, minutes_map = build_transcript_views(segs)

            if args.format == "seg":
                output = per_seg
            elif args.format == "chunk":
                chunks = chunk_transcript(minutes_map)
                output = json.dumps(chunks, ensure_ascii=False, indent=2)
            elif args.format == "json":
                output = json.dumps(segs, ensure_ascii=False, indent=2)
            else:
                output = per_min

            if args.out:
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(output)
                print(f"已保存到: {args.out}")
            else:
                print(output)

        elif args.command == "slides":
            parsed = parse_lecture_url(args.url)
            sub_id = parsed["sub_id"]
            tenant = parsed.get("tenant_code", "112")
            cookie = _load_cookie(args.cookie or "", args.cookie_file or "")
            slides = fetch_slides(sub_id, tenant, cookie)
            md = format_slides_as_markdown(slides)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(md)
                print(f"已保存到: {args.out}")
            else:
                print(md or "未获取到 PPT 数据")

        elif args.command == "courseware":
            try:
                text = extract_courseware_text(args.file, args.max_chars)
            except CoursewareError as exc:
                print(f"提取失败: {exc}", file=sys.stderr)
                sys.exit(1)
            print(text)

        elif args.command == "cookie":
            c = get_edge_cookie()
            if not c:
                print("未能在本机 Edge 找到 classroom.zju.edu.cn 的 Cookie。")
                return
            if args.reveal:
                print("读取成功（明文回显；注意终端历史）：")
                print(c)
                return
            info = describe_cookie(c)
            print(
                "读取成功（默认不显示明文）："
                f"\n  Cookie 数量: {info['cookie_count']}"
                f"\n  Cookie 名称: {', '.join(info['cookie_names'])}"
                f"\n  总长度: {info['total_length']} 字符"
            )
            print("  如需明文请加 --reveal（不建议在共享终端使用）。")

        elif args.command == "mcp":
            _run_mcp_server()

    except Exception as e:
        print(f"执行失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
