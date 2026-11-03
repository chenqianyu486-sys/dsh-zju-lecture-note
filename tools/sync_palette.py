#!/usr/bin/env python3
"""把 prelude.typ 的 soft-palette 同步到讲义模板与 handout.py。

单一来源：``zju_lecture/prelude.typ`` 里的 ``#let soft-palette``
生成副本：
  * ``zju_lecture/handout_prelude.typ`` 的 ``#let palette``（讲义 PDF 模板，自包含，不能 import）
  * ``zju_lecture/handout.py`` 的 ``_PALETTE``（Python 侧渲染 GitHub alert 色块时用）

改配色只改 prelude，然后跑本脚本；``--check`` 只检查不写盘，有漂移时退出码为 1。
``tests/test_palette_sync.py`` 用 ``--check`` 守住三处一致，并校验对比度。

用法::

    python tools/sync_palette.py          # 同步
    python tools/sync_palette.py --check  # 只检查
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE = os.path.join(ROOT, "zju_lecture", "prelude.typ")
HANDOUT_TYP = os.path.join(ROOT, "zju_lecture", "handout_prelude.typ")
HANDOUT_PY = os.path.join(ROOT, "zju_lecture", "handout.py")

#: 讲义链路用到的全部角色，顺序固定（生成的文本才能幂等）。
ROLES: Tuple[str, ...] = (
    "bg",
    "ink",
    "muted",
    "hairline",
    "thm",
    "def",
    "eg",
    "warn",
    "rule",
    "fillin",
)

#: 每个角色的用途，只出现在生成物的行尾注释里。
NOTES: Dict[str, str] = {
    "bg": "纸白：页面底色",
    "ink": "正文",
    "muted": "页码 / 边注 / aside",
    "hairline": "分隔线 / 书写位横线",
    "thm": "蓝 · 结论族",
    "def": "青绿 · 定义族",
    "eg": "琥珀 · 例子族",
    "warn": "紫 · 易错（项目扩展）",
    "rule": "标题下横线",
    "fillin": "填空线",
}

_SOURCE_RE = re.compile(r"#let soft-palette = \((?P<body>.*?)\n\)", re.S)
_ROLE_RE = re.compile(r'^\s*(?P<role>[a-z]+):\s*rgb\("(?P<hex>#[0-9A-Fa-f]{6})"\)', re.M)
_TYP_RE = re.compile(r"#let palette = \(\n(?P<body>.*?)\n\)", re.S)
_PY_RE = re.compile(r"#: [^\n]*palette[^\n]*\n_PALETTE = \{(?P<body>.*?)\n\}", re.S)
_PY_ENTRY_RE = re.compile(r'"(?P<role>[a-z]+)":\s*"(?P<hex>#[0-9A-Fa-f]{6})"')


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def read_source_palette() -> Dict[str, str]:
    """从 prelude.typ 抽出 soft-palette 的 ``role -> #RRGGBB``。"""
    match = _SOURCE_RE.search(_read(SOURCE))
    if match is None:
        raise ValueError("prelude.typ 里找不到 `#let soft-palette = (` 块")
    palette = {
        item.group("role"): item.group("hex").upper()
        for item in _ROLE_RE.finditer(match.group("body"))
    }
    missing = [role for role in ROLES if role not in palette]
    if missing:
        raise ValueError("soft-palette 缺角色: " + ", ".join(missing))
    return palette


def read_current(path: str, kind: str) -> Dict[str, str]:
    """读某个生成物当前的 palette（kind 为 ``typ`` 或 ``py``）。"""
    text = _read(path)
    pattern = _PY_RE if kind == "py" else _TYP_RE
    match = pattern.search(text)
    if match is None:
        raise ValueError("%s 里找不到 palette 块" % os.path.relpath(path, ROOT))
    body = match.group("body")
    if kind == "py":
        return {
            item.group("role"): item.group("hex").upper()
            for item in _PY_ENTRY_RE.finditer(body)
        }
    return {
        item.group("role"): item.group("hex").upper()
        for item in _ROLE_RE.finditer(body)
    }


def render_typ(palette: Dict[str, str]) -> str:
    """生成 handout_prelude.typ 的 ``#let palette`` 块。"""
    rows = ['  %s: rgb("%s"),' % (role, palette[role]) for role in ROLES]
    width = max(len(row) for row in rows) + 1
    lines = ["#let palette = ("]
    for role, row in zip(ROLES, rows):
        lines.append(row.ljust(width) + "// " + NOTES[role])
    lines.append(")")
    return "\n".join(lines)


def render_py(palette: Dict[str, str]) -> str:
    """生成 handout.py 里的 ``_PALETTE`` 字典。"""
    lines = [
        "#: 与 prelude.typ 的 soft-palette 逐角色一致；由 tools/sync_palette.py 生成，不要手改。",
        "_PALETTE = {",
    ]
    for role in ROLES:
        lines.append('    "%s": "%s",' % (role, palette[role]))
    lines.append("}")
    return "\n".join(lines)


def plan() -> Tuple[Dict[str, str], List[Tuple[str, str, str]]]:
    """返回 ``(源 palette, [(路径, 原文, 新文), ...])``。"""
    palette = read_source_palette()
    targets = (
        (HANDOUT_TYP, "typ", _TYP_RE, render_typ(palette)),
        (HANDOUT_PY, "py", _PY_RE, render_py(palette)),
    )
    edits: List[Tuple[str, str, str]] = []
    for path, _kind, pattern, rendered in targets:
        text = _read(path)
        if pattern.search(text) is None:
            raise ValueError("%s 里找不到待替换的 palette 块" % os.path.relpath(path, ROOT))
        edits.append((path, text, pattern.sub(lambda _match, block=rendered: block, text, count=1)))
    return palette, edits


def main(argv: List[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover - Python < 3.7
        pass

    check = "--check" in argv
    try:
        palette, edits = plan()
    except (OSError, ValueError) as exc:
        print("同步失败: %s" % exc, file=sys.stderr)
        return 2

    if check:
        problems: List[str] = []
        for path, kind in ((HANDOUT_TYP, "typ"), (HANDOUT_PY, "py")):
            current = read_current(path, kind)
            for role in ROLES:
                if current.get(role) != palette[role]:
                    problems.append(
                        "%s: %s 是 %s，应为 %s"
                        % (
                            os.path.relpath(path, ROOT),
                            role,
                            current.get(role) or "(缺失)",
                            palette[role],
                        )
                    )
        if problems:
            for line in problems:
                print("调色板漂移 — " + line, file=sys.stderr)
            print("跑 python tools/sync_palette.py 同步。", file=sys.stderr)
            return 1
        print("调色板一致：prelude.typ / handout_prelude.typ / handout.py")
        return 0

    changed = 0
    for path, before, after in edits:
        if before == after:
            continue
        if "--dry-run" in argv:
            print("将更新: %s" % os.path.relpath(path, ROOT))
            changed += 1
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(after)
        print("已更新: %s" % os.path.relpath(path, ROOT))
        changed += 1
    if not changed:
        print("无需更新：三处调色板已经一致")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
