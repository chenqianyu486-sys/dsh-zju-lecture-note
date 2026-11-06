# -*- coding: utf-8 -*-
"""
Command-line interface for ZJU Lecture tools.
"""

import argparse
import json
import os
import sys

from .browser_login import (
    LoginError,
    clear_session,
    load_session_cookie,
    login_available,
    open_login_window,
    session_summary,
)
from .client import (
    BASE_URL,
    TranscriptAuthError,
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
from .paths import artifact_dir
from .security import describe_cookie, sanitize_cookie_header


def _confirm_cookie_reveal() -> bool:
    """Ask for a second confirmation before printing a Cookie in clear text.

    ``--reveal`` puts a live session credential into the terminal scrollback
    and shell history. A non-interactive invocation (CI, a pipe) is refused
    outright; an interactive one must type ``yes``.
    """
    if not sys.stdin.isatty():
        print(
            "已拒绝 --reveal：非交互式终端不显示 Cookie 明文。"
            "如需本机排查，请在终端里交互执行，或改用 `zju-lecture login`。",
            file=sys.stderr,
        )
        return False
    try:
        answer = input("将回显 Cookie 明文（会进入终端历史），输入 yes 继续：")
    except EOFError:
        return False
    if answer.strip().lower() != "yes":
        print("已取消。")
        return False
    return True


def _read_cookie_file(path: str) -> str:
    """Read a cookie header from a local file (never printed)."""
    with open(os.path.expanduser(path), "r", encoding="utf-8") as handle:
        raw = handle.readline().strip()
    return sanitize_cookie_header(raw)


def _load_cookie(explicit: str = "", cookie_file: str = "") -> str:
    """Resolve a cookie: explicit > file > ZJU_COOKIE > zju_login session > Edge."""
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
    saved = load_session_cookie()
    if saved:
        return saved
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
    p_fetch = subparsers.add_parser("fetch", help="抓取课程语音识别字幕（可能需要登录态）")
    p_fetch.add_argument("url", help="回放 URL 或 sub_id")
    p_fetch.add_argument(
        "--no-login",
        action="store_true",
        help="匿名请求被拒绝时不使用本机登录态（默认会自动读取本地登录态重试一次）",
    )
    p_fetch.add_argument(
        "--cookie-file",
        help="匿名请求被拒绝时，从指定本地文件读取登录态（不要传 Cookie 明文）",
    )
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
    p_slides = subparsers.add_parser(
        "slides",
        help="抓取课堂投影 PPT 截图清单（可下载为 PDF，需 Cookie）",
    )
    p_slides.add_argument("url", help="回放 URL 或 sub_id")
    p_slides.add_argument(
        "--course-id",
        help="课程 ID；只传纯 sub_id 时必须提供（完整 URL 会自动解析）",
    )
    p_slides.add_argument(
        "--cookie-file",
        help="从文件读取 Cookie（推荐；避免出现在进程列表与 shell 历史里）",
    )
    p_slides.add_argument(
        "--cookie",
        help="直接传 Cookie 字符串（会出现在进程列表，已不推荐；留空则依次尝试 "
             "--cookie-file / ZJU_COOKIE / 本机 Edge）",
    )
    p_slides.add_argument(
        "--download",
        action="store_true",
        help="下载截图到工作区并合成 PDF",
    )
    p_slides.add_argument(
        "--out-dir",
        help="截图与 PDF 的输出目录（相对当前工作区，默认 ppt-assets/<sub_id>）",
    )
    p_slides.add_argument(
        "--no-dedup",
        action="store_true",
        help="不折叠连续重复截图（只影响 PDF 页数）",
    )
    p_slides.add_argument("--out", "-o", help="输出 Markdown 路径")

    # Command: courseware
    p_cw = subparsers.add_parser("courseware", help="从本地课件文件提取文字 (pptx/docx/txt/md/pdf)")
    p_cw.add_argument("file", help="课件文件路径")
    p_cw.add_argument("--max-chars", type=int, default=10000, help="最多提取字符数")

    # Command: login
    p_login = subparsers.add_parser(
        "login",
        help="打开独立登录窗口完成浙大登录，并安全保存本机登录态",
    )
    p_login.add_argument(
        "url",
        nargs="?",
        default="",
        help="登录后要打开的课堂链接（可选，仅接受 https 的 *.zju.edu.cn）",
    )
    p_login.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="等待完成登录的秒数（默认 300，范围 30–540）",
    )
    p_login.add_argument(
        "--clear",
        action="store_true",
        help="清除本机保存的登录态与独立登录窗口配置（不打开窗口）",
    )

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
            try:
                segs = fetch_transcript(sub_id, tenant)
            except TranscriptAuthError as exc:
                if args.no_login:
                    raise ZJUAPIError(f"{exc}已按 --no-login 禁用本机登录态。") from exc
                cookie = _load_cookie(cookie_file=args.cookie_file or os.environ.get("ZJU_COOKIE_FILE", ""))
                if not cookie:
                    raise ZJUAPIError(
                        f"{exc}未读取到本机登录态；运行 `zju-lecture login` 打开独立登录窗口，"
                        "或使用 --cookie-file 指定本地 Cookie 文件（高级兜底）。"
                    ) from exc
                try:
                    segs = fetch_transcript(sub_id, tenant, cookie=cookie)
                except TranscriptAuthError as auth_exc:
                    raise ZJUAPIError(
                        f"携带本地登录态后仍返回 HTTP {auth_exc.status}，已停止重试；"
                        "请确认官网字幕权限并更新本机登录态。"
                    ) from auth_exc

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
            # Optional module: keep transcript-only CLI invocations free of the
            # screenshot/PDF pipeline.
            from .slides import build_slides_pdf, download_slides

            parsed = parse_lecture_url(args.url)
            sub_id = parsed["sub_id"]
            tenant = parsed.get("tenant_code", "112")
            course_id = args.course_id or parsed.get("course_id", "")
            cookie = _load_cookie(args.cookie or "", args.cookie_file or "")
            diagnostics = []
            slides = fetch_slides(
                sub_id,
                tenant,
                cookie,
                diagnostics=diagnostics,
                course_id=course_id,
            )
            if not slides:
                print("未获取到 PPT 截图：")
                for item in diagnostics or ["未获得具体原因"]:
                    print(f"- {item}")
                sys.exit(1)

            pdf_path = ""
            if args.download:
                target, error = artifact_dir(
                    args.out_dir or "",
                    default=os.path.join("ppt-assets", sub_id),
                )
                if error:
                    print(f"输出目录不可用: {error}", file=sys.stderr)
                    sys.exit(1)
                summary = download_slides(
                    slides,
                    target,
                    cookie=cookie,
                    sub_id=sub_id,
                    dedup=not args.no_dedup,
                    diagnostics=diagnostics,
                )
                pages = summary.get("pages") or []
                if pages:
                    pdf_path = build_slides_pdf(
                        pages,
                        os.path.join(target, f"PPT-{sub_id}.pdf"),
                        diagnostics=diagnostics,
                    ) or ""
                print(
                    f"截图: 下载 {summary.get('downloaded', 0)} 张，"
                    f"失败 {summary.get('failed', 0)} 张，"
                    f"连续重复折叠 {summary.get('duplicates', 0)} 张"
                )
                print(f"截图目录: {summary.get('images_dir')}")
                if pdf_path:
                    print(f"PDF: {pdf_path}（{len(pages)} 页）")

            md = format_slides_as_markdown(slides, pdf_path=pdf_path)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(md)
                print(f"已保存到: {args.out}")
            else:
                print(md)
            for item in diagnostics:
                print(f"提示: {item}", file=sys.stderr)

        elif args.command == "courseware":
            try:
                text = extract_courseware_text(args.file, args.max_chars)
            except CoursewareError as exc:
                print(f"提取失败: {exc}", file=sys.stderr)
                sys.exit(1)
            print(text)

        elif args.command == "login":
            if args.clear:
                result = clear_session(delete_profile=True)
                print(
                    "已清除本机登录态。"
                    if result.get("session_removed")
                    else "本机没有保存的登录态。"
                )
                if result.get("profile_removed"):
                    print("独立登录窗口的浏览器配置也已删除。")
                if result.get("profile_error"):
                    print(
                        "独立登录窗口配置未能删除："
                        f"{result['profile_error']}。请先关闭该窗口后重试。",
                        file=sys.stderr,
                    )
                return
            try:
                result = open_login_window(args.url, args.timeout)
            except LoginError as exc:
                print(f"登录未完成（{exc.reason}）：{exc.message}", file=sys.stderr)
                if exc.hint:
                    print(f"下一步：{exc.hint}", file=sys.stderr)
                sys.exit(1)
            print("登录成功，已读取本机登录态。")
            print(f"- 浏览器: {result['browser']}")
            print(f"- Cookie: {len(result['names'])} 条（含 _token，值不回显）")
            if result.get("saved"):
                print(f"- 保存: {result['saved_path']}（仅当前系统用户可解密）")
            else:
                print(f"- 保存失败: {result.get('save_error') or '未知原因'}（本次会话可用）")
            print("现在可以运行 `zju-lecture fetch <url>`。")

        elif args.command == "cookie":
            if args.reveal and not _confirm_cookie_reveal():
                return
            c = get_edge_cookie()
            if not c:
                print("未能在本机 Edge 找到 classroom.zju.edu.cn 的 Cookie。")
                print("推荐改用 `zju-lecture login`：它会打开独立登录窗口，不依赖 Edge 的 Cookie 解密。")
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
