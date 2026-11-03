#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把随包分发的 prelude 同步到 Skill 目录。

`zju_lecture/prelude.typ` 是**唯一权威副本**：它随 Python 包分发，
`zju_build_study_notes` 在编译时把它写进项目目录。Skill 目录下的
`references/prelude.typ` 只是给人和 Agent 阅读的副本，必须与权威副本
逐字节一致 —— 两份各改各的，就会出现「按 Skill 改了配色、编译出来没变」
这种最难查的问题。

所以：改配色只改 `zju_lecture/prelude.typ`，然后跑这个脚本。
`tests/test_study_notes.py` 会校验两者一致。

用法：
    python tools/sync_skill_assets.py [--check]
"""

import argparse
import filecmp
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: (权威副本, 生成副本)
ASSETS = [
    (
        os.path.join(ROOT, "zju_lecture", "prelude.typ"),
        os.path.join(ROOT, "skills", "scholia-notes", "references", "prelude.typ"),
    ),
]


def sync(check_only=False):
    """Copy (or verify) every generated asset. Returns a list of problems."""
    problems = []
    for source, target in ASSETS:
        if not os.path.isfile(source):
            problems.append(f"缺少权威副本: {source}")
            continue
        if check_only:
            if not os.path.isfile(target):
                problems.append(f"缺少生成副本: {target}")
            elif not filecmp.cmp(source, target, shallow=False):
                problems.append(
                    f"生成副本与权威副本不一致: {os.path.relpath(target, ROOT)}\n"
                    f"    请执行: python tools/sync_skill_assets.py"
                )
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
        print(f"已同步: {os.path.relpath(target, ROOT)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查一致性，不写入（发布闸门用）",
    )
    args = parser.parse_args()

    problems = sync(check_only=args.check)
    if problems:
        for item in problems:
            print(f"错误: {item}", file=sys.stderr)
        return 1
    if args.check:
        print("Skill 资产与权威副本一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
