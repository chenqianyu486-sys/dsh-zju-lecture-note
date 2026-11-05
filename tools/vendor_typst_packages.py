#!/usr/bin/env python3
"""把填空笔记链路依赖的 Typst 包 vendor 进 ``zju_lecture/typst-packages``。

为什么 vendor
-------------
``@preview/scholia`` 一系默认在**首次编译时**从 Typst 包注册表联网拉取。离线、
校园网拦截或 registry 抖动时，填空笔记会直接编译失败。把源码放进包里并给
``typst compile`` 传 ``--package-path``，就能彻底离线。

许可
----
- MIT：保留每个包的 ``LICENSE`` 与 ``typst.toml``（``typst.toml`` 是 Typst
  解析 ``@preview/name:version`` 的依据，不能删）。
- Unlicense：保留 ``UNLICENSE`` 文本（公有领域，保留是零成本的好习惯）。

只删文档：``README.md`` / ``README.typ`` / ``template/``。``frame-it`` 的
``README.md`` 有 3.8MB（示例图），删掉还顺带消除来源不明素材的风险。

用法::

    python tools/vendor_typst_packages.py --from-cache
    python tools/vendor_typst_packages.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "zju_lecture", "typst-packages")
RAW = "https://raw.githubusercontent.com/typst/packages/main/packages/preview/{name}/{version}/{path}"

# 包名 → 版本。顺序即依赖顺序，仅用于可读性。
PACKAGES = {
    "scholia": "0.1.0",
    "frame-it": "2.0.0",
    "marginalia": "0.3.1",
    "theoretic": "0.3.1",
    "showybox": "2.0.4",
    "noteworthy": "0.4.0",
}

#: 对上游源码打的补丁：``(相对路径, 上游片段, 本项目片段, 说明)``。
#:
#: 只改 scholia：字体表是商业字体问题的根源；标题字号/边注段距让两条 PDF
#: 链路统一到同一套排版规范。补丁必须能重放——重新 vendor 时自动应用，
#: 否则下次 ``--from-cache`` 会把改动冲掉。``--check`` 会验证补丁已生效。
PATCHES = {
    "scholia": [
        (
            "src/fonts.typ",
            """#let default-fonts = (
  body: ("STIX Two Text", "Libertinus Serif"),
  math: ("STIX Two Math", "New Computer Modern Math"),
  heading: ("Optima", "Libertinus Serif"),
  sans: ("Avenir Next", "Libertinus Serif"), // the informal "intuition voice"
  mono: ("Menlo", "DejaVu Sans Mono"),
  cjk: ("Songti SC",), // appended after body/sans for 中文 glyph fallback
)""",
            """#let default-fonts = (
  body: ("STIX Two Text", "Libertinus Serif"),
  math: ("STIX Two Math", "New Computer Modern Math"),
  heading: (
    "STIX Two Text", "Libertinus Serif",
    "Notes Kai SC", "Notes Serif SC", "Noto Serif SC", "Source Han Serif SC",
  ),
  sans: (
    "Noto Sans", "Liberation Sans", "DejaVu Sans",
    "Notes Kai SC", "Notes Serif SC", "Noto Serif SC", "Source Han Serif SC",
  ),
  mono: ("DejaVu Sans Mono", "Notes Kai SC", "Notes Serif SC"),
  cjk: ("Notes Kai SC", "Notes Serif SC", "Noto Serif SC", "Source Han Serif SC"),
)""",
            "sans 换成可再分发的无衬线（Noto Sans / Liberation / DejaVu），方框标签与直觉块才有另一族的字形；中文仍走随包 Notes Kai SC —— 本机 Noto Sans SC 是可变字体、Typst 只会取到 Thin，排出来发灰，所以不放进栈里",
        ),
        (
            "src/theorems.typ",
            'text(font: default-fonts.heading, weight: "bold", fill: a)[#supplement #number]',
            'text(font: default-fonts.sans, weight: "bold", fill: a)[#supplement #number]',
            "方框标签改用 sans（上游用 Optima，也是无衬线；heading 现在是衬线，"
            "标签会糊在正文里没有层次）",
        ),
        (
            "src/theorems.typ",
            'text(font: default-fonts.heading, weight: "bold", fill: a)[.]',
            'text(font: default-fonts.sans, weight: "bold", fill: a)[.]',
            "方框标签末尾的句点跟着标签一起换 sans",
        ),
        (
            "src/lib.typ",
            'text(font: default-fonts.heading, weight: "bold", fill: p.eg)[Your turn.]',
            'text(font: default-fonts.sans, weight: "bold", fill: p.eg)[Your turn.]',
            "练习块标签与方框标签同族（sans）",
        ),
        (
            "src/lib.typ",
            "set par(leading: 0.5em)",
            "set par(leading: 0.5em, spacing: 0.4em)",
            "边注段距补 0.4em，与阅读版一致",
        ),
        (
            "src/lib.typ",
            '#text(font: hfont, weight: "bold", fill: p.def)[#counter(heading).display() #it.body]',
            '#text(font: hfont, weight: "bold", size: 12.5pt, fill: p.def)[#counter(heading).display() #it.body]',
            "二级标题字号统一为 12.5pt",
        ),
        (
            "src/lib.typ",
            '#text(font: f.sans, weight: "bold", fill: p.thm)[#it.body]',
            '#text(font: f.sans, weight: "bold", size: 11.5pt, fill: p.thm)[#it.body]',
            "三级标题字号统一为 11.5pt",
        ),
        (
            "src/lib.typ",
            "block(above: 20pt, below: 8pt, width: 100%)[",
            "block(above: 24pt, below: 12pt, width: 100%)[",
            "一级标题上 24pt / 下 12pt（2.2.4：章与节都多留一点空）",
        ),
        (
            "src/lib.typ",
            "show heading.where(level: 2): it => block(above: 11pt, below: 0.5em)[",
            "show heading.where(level: 2): it => block(above: 22pt, below: 0.85em)[",
            "二级标题上 22pt、下 0.85em（上边距 2.2.4 由 12pt 加大，节与正文分得开）",
        ),
        (
            "src/lib.typ",
            "show heading.where(level: 3): it => block(above: 8pt, below: 0.5em)[",
            "show heading.where(level: 3): it => block(above: 9pt, below: 0.65em)[",
            "三级标题后的间距加大到 0.65em（2.2.2）",
        ),
    ],
}


def apply_patches(destination: str, name: str) -> None:
    """把本项目对上游源码的补丁重放到刚 vendor 的目录。"""
    for relative, old, new, note in PATCHES.get(name, ()):
        path = os.path.join(destination, relative)
        if not os.path.isfile(path):
            raise SystemExit(f"{_manifest(name, '?')} 缺少补丁目标 {relative}")
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if new in text:
            continue
        if old not in text:
            raise SystemExit(
                f"补丁无法应用：{_manifest(name, '?')}/{relative} 与预期上游内容不一致。\n"
                f"  补丁说明：{note}\n"
                "  上游版本变了就更新 tools/vendor_typst_packages.py 里的补丁片段。"
            )
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.replace(old, new, 1))


# 只删文档与模板，代码、许可、清单都保留。
DROP_FILES = {"README.md", "README.typ"}
DROP_DIRS = {"template", "tests", "examples", "docs"}

LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "UNLICENSE", "COPYING")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(name: str, version: str) -> str:
    return f"@preview/{name}:{version}"


def copy_package(source_root: str, name: str, version: str) -> dict:
    source = os.path.join(source_root, name, version)
    if not os.path.isdir(source):
        raise SystemExit(
            f"找不到源包 {_manifest(name, version)}：{source}\n"
            "先在一个有网的机器上编译一次填空笔记，或手动解压 registry 缓存后再跑本脚本。"
        )

    destination = os.path.join(TARGET, "preview", name, version)
    if os.path.isdir(destination):
        shutil.rmtree(destination)
    os.makedirs(destination, exist_ok=True)

    files = []
    for current, dirs, names in os.walk(source):
        dirs[:] = [d for d in dirs if d not in DROP_DIRS]
        relative = os.path.relpath(current, source)
        for file_name in names:
            if file_name in DROP_FILES:
                continue
            source_file = os.path.join(current, file_name)
            target_dir = destination if relative == "." else os.path.join(destination, relative)
            os.makedirs(target_dir, exist_ok=True)
            shutil.copyfile(source_file, os.path.join(target_dir, file_name))
            files.append(os.path.join(relative, file_name).replace(".\\", "/"))

    licences = [name for name in os.listdir(destination) if name in LICENSE_NAMES]
    if not licences:
        raise SystemExit(f"{_manifest(name, version)} 没有许可文件，拒绝 vendor。")

    apply_patches(destination, name)

    return {
        "name": name,
        "version": version,
        "license_file": licences[0],
        "files": sorted(files),
    }


def download_package(name: str, version: str) -> dict:
    """从 GitHub 的 typst/packages 仓库逐文件下载（网络可用时的备选路径）。"""
    import ssl

    try:
        from zju_lecture.client import get_ssl_context

        context = get_ssl_context()
    except Exception:  # noqa: BLE001
        context = ssl.create_default_context()

    destination = os.path.join(TARGET, "preview", name, version)
    if os.path.isdir(destination):
        shutil.rmtree(destination)
    os.makedirs(destination, exist_ok=True)

    # 包内文件清单无法通过 API 稳定枚举，这里只下载已知必要文件：
    # typst.toml、许可、lib.typ 与 src/。其余（README/template）本来就要删。
    known = ["typst.toml", "lib.typ"]
    for license_name in LICENSE_NAMES:
        known.append(license_name)
    for index in range(1, 12):
        known.append(f"src/part{index}.typ")
    if name == "scholia":
        # 本项目的补丁目标；下载路径不完整，但至少把被改的文件拿全。
        known += ["src/fonts.typ", "src/lib.typ", "src/colors.typ",
                  "src/theorems.typ", "src/visual.typ"]

    downloaded = []
    for path in known:
        url = RAW.format(name=name, version=version, path=path)
        request = urllib.request.Request(url, headers={"User-Agent": "zju-lecture-plugin/vendor"})
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                data = response.read()
        except Exception:  # noqa: BLE001 - 404 是正常情况
            continue
        target = os.path.join(destination, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
        downloaded.append(path)

    # src/ 下的真实文件名无法预先枚举：回退到 curl 目录列表太脆弱，直接要求
    # 用户用 --from-cache。这里只验证最小可用集。
    if "typst.toml" not in downloaded:
        raise SystemExit(f"下载 {_manifest(name, version)} 失败（网络或路径变化）。")

    apply_patches(destination, name)

    return {
        "name": name,
        "version": version,
        "license_file": next((p for p in downloaded if p in LICENSE_NAMES), ""),
        "files": sorted(downloaded),
    }


def write_index(entries: list) -> None:
    path = os.path.join(TARGET, "VENDORED.md")
    lines = [
        "# Vendored Typst packages",
        "",
        "本目录是**随包分发的第三方代码**，不是本项目原创。编译时通过",
        "`typst compile --package-path <本目录>` 解析 `@preview/…`，因此填空笔记",
        "链路不需要联网。",
        "",
        "| 包 | 版本 | 许可 | 许可文件 | 文件数 |",
        "| :--- | :--- | :--- | :--- | ---: |",
    ]
    for entry in entries:
        lines.append(
            f"| `@preview/{entry['name']}` | {entry['version']} | "
            f"{entry['license']} | `{entry['license_file']}` | {len(entry['files'])} |"
        )
    lines += [
        "",
        "## 来源与修改",
        "",
        f"- 来源：<https://github.com/typst/packages>（Typst Universe registry 的公开仓库），",
        "  逐个包按 `packages/preview/<name>/<version>/` 取用。",
        "- 删除：`README.md` / `README.typ` / `template/` / `tests/` / `examples/` / `docs/`。",
        "- frame-it 的 `README.md` 有 3.8MB（示例图），删除它同时避免分发来源不明的素材。",
        "- **修改**：`@preview/scholia` 0.1.0 打了以下补丁（由",
        "  `tools/vendor_typst_packages.py` 重放，重新 vendor 时会自动应用）：",
        "",
        "| 文件 | 修改 |",
        "| :--- | :--- |",
        "| `src/fonts.typ` | 字体表改为可再分发栈：`body`/`heading` 用 STIX Two + 随包 Notes Kai SC、Notes Serif SC；`sans` 用 Noto Sans / Liberation Sans / DejaVu Sans（中文回 Notes Kai SC）；移除 Optima / Avenir Next / Menlo / Songti SC |",
        "| `src/theorems.typ` | 方框标签（`Theorem` / `Definition` / `Example`）改用 `default-fonts.sans`，标签末尾句点同步 |",
        "| `src/lib.typ` | `Your turn.` 标签改用 `sans`；二级/三级标题字号统一为 12.5pt / 11.5pt；一/二级标题上方留白 24pt / 22pt；边注段距补 0.4em |",
        "",
        "  除上述补丁外，其余代码、`typst.toml` 与许可文件保持上游原样。",
        "",
        "## 许可",
        "",
        "MIT 包（scholia / frame-it / showybox / noteworthy）要求保留版权声明与许可全文；",
        "本目录逐个包保留了 `LICENSE`。Unlicense 包（marginalia / theoretic）保留",
        "`UNLICENSE` 文本。这些文件**必须随 npm 包与 MCode 包一起分发**，",
        "否则等于分发了代码却不带许可。",
        "",
        "逐条归属见仓库根目录 `ATTRIBUTION.md` 与 `skills/scholia-notes/THIRD_PARTY_NOTICES.md`。",
        "",
    ]
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))


def check() -> int:
    index = os.path.join(TARGET, "VENDORED.md")
    if not os.path.isfile(index):
        print("VENDORED.md 不存在，先运行 vendor 脚本。")
        return 1
    problems = 0
    for name, version in PACKAGES.items():
        directory = os.path.join(TARGET, "preview", name, version)
        if not os.path.isdir(directory):
            print(f"✗ 缺少 @preview/{name}:{version}")
            problems += 1
            continue
        licences = [f for f in os.listdir(directory) if f in LICENSE_NAMES]
        manifest = os.path.join(directory, "typst.toml")
        if not licences:
            print(f"✗ @preview/{name}:{version} 缺许可文件")
            problems += 1
        if not os.path.isfile(manifest):
            print(f"✗ @preview/{name}:{version} 缺 typst.toml")
            problems += 1
        for relative, _old, new, note in PATCHES.get(name, ()):
            path = os.path.join(directory, relative)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    text = handle.read()
            except OSError:
                print(f"✗ @preview/{name}:{version} 缺补丁目标 {relative}")
                problems += 1
                continue
            if new not in text:
                print(f"✗ @preview/{name}:{version}/{relative} 未打补丁：{note}")
                problems += 1
        if not problems:
            print(f"✓ @preview/{name}:{version}")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-cache", action="store_true",
                        help="从本机 Typst 包缓存复制（推荐，内容与 registry 一致）")
    parser.add_argument("--download", action="store_true",
                        help="从 typst/packages 仓库下载（文件枚举不完整，仅作兜底）")
    parser.add_argument("--cache-dir", default="",
                        help="Typst 包缓存目录；默认按平台猜")
    parser.add_argument("--check", action="store_true", help="只校验已 vendor 的包")
    args = parser.parse_args()

    if args.check:
        return check()

    cache = args.cache_dir or guess_cache_dir()
    if not args.download and not args.from_cache:
        args.from_cache = True

    entries = []
    for name, version in PACKAGES.items():
        if args.from_cache:
            entry = copy_package(cache, name, version)
        else:
            entry = download_package(name, version)
        entry["license"] = _license_name(entry["name"], args.from_cache, cache, version)
        entries.append(entry)
        print(f"✓ @preview/{name}:{version}  {len(entry['files'])} 个文件")

    write_index(entries)
    print(f"\n写入 {TARGET}")
    return 0


def _license_name(name: str, from_cache: bool, cache: str, version: str) -> str:
    if not from_cache:
        return "见文件"
    manifest = os.path.join(cache, name, version, "typst.toml")
    try:
        with open(manifest, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip().startswith("license"):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "未知"


def guess_cache_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
        return os.path.join(base, "typst", "packages", "preview")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Caches/typst/packages/preview")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "typst", "packages", "preview")


if __name__ == "__main__":
    raise SystemExit(main())
