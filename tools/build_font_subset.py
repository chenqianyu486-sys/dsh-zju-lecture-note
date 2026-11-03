#!/usr/bin/env python3
"""生成随包分发的中文子集字体。

为什么要子集
------------
两条 PDF 链路都要「任何机器都出字、标题有真正的粗体、PDF 可以对外分享」。
系统字体满足不了：干净的 Windows 只有 SimSun（没有粗体面，Typst 不会合成），
而 SimSun / KaiTi 本身是微软专有字体，把它们的子集嵌进 PDF 再对外分享是有
许可风险的。

做法
----
- **Notes Serif SC**：Google Fonts 的 Noto Serif SC 变量字体（SIL OFL 1.1，
  **没有** Reserved Font Name 声明，所以允许子集化与再分发）。
- **Notes Kai SC**：LXGW WenKai（霞鹜文楷，SIL OFL 1.1，**有** Reserved Font
  Name；因此必须改名，衍生字体不得继续使用 `霞鹜` / `LXGW` 等名字）。
- 字符集：GB2312 全集 + ASCII + 常用标点与数学符号（约 7.5k 字）。生僻字不在
  子集里也没关系——Typst 会按字体族列表逐字回退。
- **改名**：两个子集都不再使用上游名字。一是避免和用户本机完整版重名（Typst
  选中哪个不确定），二是避免让人误以为是完整字体，三是避开上游商标。
- 许可：字体继续以 OFL 1.1 分发，``OFL.txt`` / ``OFL-Kai.txt`` 与
  ``FONT-NOTICE.md`` 随包。

用法::

    python tools/build_font_subset.py            # 下载两个源字体后生成
    python tools/build_font_subset.py --check    # 只校验产物与元数据
    python tools/build_font_subset.py --font kai --kai-source <path>
"""

from __future__ import annotations

import argparse
import hashlib
import os
import ssl
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(ROOT, "zju_lecture", "fonts")

#: 两个随包字体。``upstream`` 是子集校验时要排除的上游字样。
FONTS = {
    "serif": {
        "label": "Notes Serif SC",
        "output": "NotesSerifSC-Subset.ttf",
        "family": "Notes Serif SC",
        "ps": "NotesSerifSC-Subset",
        "source_url": (
            "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifsc/"
            "NotoSerifSC%5Bwght%5D.ttf"
        ),
        "source_sha256": "050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9",
        "source_size": 25125512,
        "license_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifsc/OFL.txt",
        "license_file": "OFL.txt",
        "upstream": ("Noto", "Google"),
        "upstream_name": "Noto Serif SC",
        "copyright": (
            "Copyright 2012 Google Inc. All Rights Reserved.；"
            "字体内部 © 2017-2023 Adobe"
        ),
        "kind": "serif",
    },
    "kai": {
        "label": "Notes Kai SC",
        "output": "NotesKaiSC-Subset.ttf",
        "family": "Notes Kai SC",
        "ps": "NotesKaiSC-Subset",
        "source_url": (
            "https://github.com/lxgw/LxgwWenKai/releases/download/v1.530/"
            "LXGWWenKai-Regular.ttf"
        ),
        "source_sha256": "2d73eea94ad808999d90c0000c239a84a33b09d4bc6ab6c5b8bbf1eda8a7fc8b",
        "source_size": 25928940,
        "license_url": "https://raw.githubusercontent.com/lxgw/LxgwWenKai/main/OFL.txt",
        "license_file": "OFL-Kai.txt",
        "upstream": ("LXGW", "霞鹜", "霞鶩", "落霞孤鹜", "落霞孤鶩"),
        "upstream_name": "LXGW WenKai",
        "copyright": (
            "Copyright 2021-2026 LXGW（霞鹜文楷）；"
            "上游声明还包含 Copyright 2020 The Klee Project Authors"
        ),
        "kind": "kai",
    },
}

# GB2312 的全部汉字 + ASCII 可见字符 + 常用标点/数学符号。
EXTRA_CHARS = (
    "，。、；：？！“”‘’（）《》〈〉【】「」『』—…·×÷±≤≥≠≈∞∑∫√°′″"
    "αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ∂∇∈∉⊂⊃⊆⊇∪∩∅∀∃¬∧∨⇒⇔→←↑↓↔"
    "①②③④⑤⑥⑦⑧⑨⑩⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽"
)


def _ssl_context() -> ssl.SSLContext:
    try:
        from zju_lecture.client import get_ssl_context

        return get_ssl_context()
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "zju-lecture-plugin/font"})
    with urllib.request.urlopen(request, timeout=300, context=_ssl_context()) as response:
        with open(target, "wb") as handle:
            handle.write(response.read())


def charset() -> str:
    chars = set()
    for high in range(0xA1, 0xF8):
        for low in range(0xA1, 0xFF):
            try:
                chars.add(bytes([high, low]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    chars.update(chr(code) for code in range(0x20, 0x7F))
    chars.update(EXTRA_CHARS)
    return "".join(sorted(chars))


def subset(source: str, output: str, spec: dict) -> None:
    from fontTools import subset as font_subset

    options = font_subset.Options()
    options.hinting = False          # Typst 自己栅格化，不需要 hinting
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.name_languages = ["*"]
    options.notdef_outline = True
    options.recommended_glyphs = True
    options.symbol_cmap = True
    options.legacy_cmap = True
    options.glyph_names = False

    font = font_subset.load_font(source, options)
    subsetter = font_subset.Subsetter(options)
    subsetter.populate(text=charset())
    subsetter.subset(font)
    font_subset.save_font(font, output, options)

    rename(output, spec)


def _set_name(table, name_id: int, value: str) -> None:
    for record in table.names:
        if record.nameID != name_id:
            continue
        try:
            record.string = value
        except Exception:  # noqa: BLE001
            pass


def rename(path: str, spec: dict) -> None:
    from fontTools.ttLib import TTFont

    font = TTFont(path)
    name = font["name"]
    _set_name(name, 1, spec["family"])
    _set_name(name, 16, spec["family"])
    _set_name(name, 4, spec["family"])
    _set_name(name, 6, spec["ps"])
    _set_name(name, 3, f"{spec['ps']};1.000")
    _set_name(name, 17, "Regular")
    _set_name(name, 21, spec["family"])
    _set_name(name, 22, "Regular")
    if 25 in {record.nameID for record in name.names}:
        _set_name(name, 25, spec["ps"])
    font.save(path)
    font.close()


def copy_license(spec: dict) -> None:
    target = os.path.join(OUT_DIR, spec["license_file"])
    if os.path.isfile(target):
        with open(target, encoding="utf-8") as handle:
            if "SIL OPEN FONT LICENSE" in handle.read():
                return
    request = urllib.request.Request(spec["license_url"], headers={"User-Agent": "zju-lecture-plugin/font"})
    with urllib.request.urlopen(request, timeout=60, context=_ssl_context()) as response:
        text = response.read().decode("utf-8")
    if "SIL OPEN FONT LICENSE" not in text:
        raise SystemExit(f"{spec['license_file']} 内容异常，拒绝写入。")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write_notice() -> None:
    notice = """# 字体声明 — Notes Serif SC / Notes Kai SC

本目录的两个 TTF 都是**子集（subset）**，不是完整字体；它们随插件分发，
用于让两条 PDF 链路在任何机器上都有中文与真正的粗体。

| 文件 | 上游 | 许可 | 版权 | 修改 |
| :--- | :--- | :--- | :--- | :--- |
| `NotesSerifSC-Subset.ttf` | Noto Serif SC（可变字体，`wght` 200–900） | SIL OFL 1.1（`OFL.txt`） | Copyright 2012 Google Inc.；字体内部 © 2017-2023 Adobe | 子集化（GB2312 + ASCII + 常用标点/数学符号）、关闭 hinting、**改名** |
| `NotesKaiSC-Subset.ttf` | LXGW WenKai（霞鹜文楷 v1.530，Regular） | SIL OFL 1.1（`OFL-Kai.txt`） | Copyright 2021-2026 LXGW；上游还包含 Copyright 2020 The Klee Project Authors | 子集化、关闭 hinting、**改名**（上游有 Reserved Font Name） |

## 覆盖范围

约 7.5k 个字符（GB2312 + ASCII + 常用标点/数学符号）。生僻字不在子集中，
由 Typst 按字体族列表回退到其他字体；若回退到 `SimSun` / `Microsoft YaHei`
等系统商业字体，那份 PDF 不宜对外分发（见 `skills/scholia-notes/references/typography-spec.md`）。

## 为什么改名

- 避免与用户本机安装的完整版 `Noto Serif SC` / `LXGW WenKai` 同名——同名时
  Typst 选哪个字体面不确定；
- 避免让人误以为拿到了完整字体；
- 避开 Noto / Source / 霞鹜 / LXGW / ZJU 商标。LXGW WenKai 的 OFL 声明包含
  Reserved Font Name，衍生字体**必须**改名。

## 分发义务

- 分发本字体（含随插件打包、随 PDF 嵌入）时必须同时提供对应的
  `OFL.txt` / `OFL-Kai.txt` 与本文件。
- OFL 允许与软件捆绑分发，但**不得单独售卖字体本身**。
- 不要把本字体改回上游名称。

## 重新生成

```bash
python tools/build_font_subset.py            # 下载两个源字体后生成
python tools/build_font_subset.py --check    # 只校验产物与元数据
```

脚本从固定 URL 下载源字体并按 SHA256 校验，所以产物可复现；源文件变更需要
显式更新脚本里的哈希。
"""
    with open(os.path.join(OUT_DIR, "FONT-NOTICE.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(notice)


def check() -> int:
    from fontTools.ttLib import TTFont

    problems = 0
    for key, spec in FONTS.items():
        path = os.path.join(OUT_DIR, spec["output"])
        if not os.path.isfile(path):
            print(f"✗ 缺少 {spec['output']}")
            problems += 1
            continue
        font = TTFont(path)
        families = {record.toUnicode() for record in font["name"].names if record.nameID in (1, 16)}
        size_mb = os.path.getsize(path) / 1e6
        if spec["family"] not in families:
            print(f"✗ {spec['output']} 字体族名不是 {spec['family']}：{families}")
            problems += 1
        if any(token in " ".join(families) for token in spec["upstream"]):
            print(f"✗ {spec['output']} 仍含上游字样：{families}")
            problems += 1
        print(
            f"✓ {spec['output']}  {size_mb:.1f} MB  族名={sorted(families)}  "
            f"变量轴={'fvar' in font}"
        )
    for required in ("OFL.txt", "OFL-Kai.txt", "FONT-NOTICE.md"):
        if not os.path.isfile(os.path.join(OUT_DIR, required)):
            print(f"✗ 缺少 {required}")
            problems += 1
    return 1 if problems else 0


def build(key: str, source_override: str = "") -> None:
    spec = FONTS[key]
    output = os.path.join(OUT_DIR, spec["output"])
    with tempfile.TemporaryDirectory() as tmp:
        if source_override:
            source = source_override
        else:
            source = os.path.join(tmp, spec["output"] + ".source")
            print(f"下载源字体 {spec['upstream_name']}：{spec['source_url']}")
            download(spec["source_url"], source)
        digest = sha256_of(source)
        if digest != spec["source_sha256"]:
            raise SystemExit(
                f"✗ {spec['upstream_name']} 源字体 SHA256 不符：{digest}\n"
                f"  期望 {spec['source_sha256']}；为确保产物可复现，请使用固定版本。"
            )
        print(f"源字体 {os.path.getsize(source)/1e6:.1f} MB，SHA256 {digest[:16]}…")
        subset(source, output, spec)
    copy_license(spec)
    print(f"写入 {output}（{os.path.getsize(output)/1e6:.1f} MB）")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", choices=sorted(FONTS), default="", help="只构建一个字体（默认两个）")
    parser.add_argument("--source", default="", help="Notes Serif SC 的本地源字体路径")
    parser.add_argument("--kai-source", default="", help="Notes Kai SC 的本地源字体路径")
    parser.add_argument("--check", action="store_true", help="只校验产物")
    args = parser.parse_args()

    if args.check:
        return check()

    os.makedirs(OUT_DIR, exist_ok=True)
    keys = [args.font] if args.font else sorted(FONTS)
    for key in keys:
        override = args.source if key == "serif" else args.kai_source
        build(key, override)
    write_notice()
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
