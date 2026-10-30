#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check a lecture-note Markdown file against the plugin's formula conventions.

Usage:
    python tools/check_note.py <note.md> [more.md ...]
    python tools/check_note.py --fix <note.md>
    python tools/check_note.py --quiet <note.md>

Exit code:
    0  no errors (warnings may still be printed)
    1  at least one error that would break rendering
    2  bad usage / unreadable file

This is the same engine the ``zju_check_note`` MCP tool uses, so a note that
passes here passes in the agent loop too.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zju_lecture.note_lint import check_markdown, fix_markdown, format_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="讲义 Markdown 渲染规范检查")
    parser.add_argument("files", nargs="+", help="待检查的讲义 Markdown 文件")
    parser.add_argument("--quiet", action="store_true", help="只输出结论，不打印逐条问题")
    parser.add_argument("--fix", action="store_true",
                        help="自动修正可机械修复的问题并回写文件")
    args = parser.parse_args()

    failed = False
    for path in args.files:
        if not os.path.isfile(path):
            print(f"FAIL: 找不到文件 {path}", file=sys.stderr)
            failed = True
            continue
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()

        applied = []
        if args.fix:
            fixed, applied = fix_markdown(text)
            if fixed != text:
                with open(path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(fixed)
                text = fixed

        issues = check_markdown(text)
        errors = [i for i in issues if i.level == "error"]
        warns = [i for i in issues if i.level == "warn"]

        if applied:
            print("=== 已自动修复 ===")
            for item in applied:
                print(f"- {item}")
            print()

        if args.quiet:
            status = "FAIL" if errors else "PASS"
            print(f"{status} {path}  错误 {len(errors)} | 警告 {len(warns)}")
        else:
            print(format_report(path, issues))
            print()

        if errors:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
