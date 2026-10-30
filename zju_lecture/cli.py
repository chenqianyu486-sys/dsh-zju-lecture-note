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
from .courseware import extract_courseware_text
from .formatter import (
    build_transcript_views,
    chunk_transcript,
    filter_segments,
    format_slides_as_markdown,
    format_timestamp,
)


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
    p_slides.add_argument("--cookie", help="Cookie 字符串，留空将尝试从 Edge 自动读取")
    p_slides.add_argument("--out", "-o", help="输出 Markdown 路径")

    # Command: courseware
    p_cw = subparsers.add_parser("courseware", help="从本地课件文件提取文字 (pptx/docx/txt/md/pdf)")
    p_cw.add_argument("file", help="课件文件路径")
    p_cw.add_argument("--max-chars", type=int, default=10000, help="最多提取字符数")

    # Command: cookie
    p_cookie = subparsers.add_parser("cookie", help="从本机 Edge 读取智云课堂 Cookie")

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
            cookie = args.cookie or get_edge_cookie()
            slides = fetch_slides(sub_id, tenant, cookie)
            md = format_slides_as_markdown(slides)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(md)
                print(f"已保存到: {args.out}")
            else:
                print(md or "未获取到 PPT 数据")

        elif args.command == "courseware":
            text = extract_courseware_text(args.file, args.max_chars)
            print(text)

        elif args.command == "cookie":
            c = get_edge_cookie()
            if c:
                print("读取成功:")
                print(c)
            else:
                print("未能在本机 Edge 找到 classroom.zju.edu.cn 的 Cookie。")

        elif args.command == "mcp":
            _run_mcp_server()

    except Exception as e:
        print(f"执行失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
