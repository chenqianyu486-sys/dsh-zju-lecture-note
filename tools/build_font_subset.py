#!/usr/bin/env python3
"""生成随包分发的中文子集字体 ``zju_lecture/fonts/NotesSerifSC-Subset.ttf``。

为什么要子集
------------
阅读版讲义要「任何机器都出字、标题有粗体、PDF 可以对外分享」。系统字体满足不了：
干净的 Windows 只有 SimSun（没有粗体面，Typst 不会合成），而 SimSun 本身是微软
专有字体，把它的子集嵌进 PDF 再对外分享是有许可风险的。

做法
----
- 源字体：Google Fonts 的 Noto Serif SC 变量字体（SIL OFL 1.1，**没有**
  Reserved Font Name 声明，所以允许子集化与再分发）。
- 字符集：GB2312 全集 + ASCII + 常用标点与数学符号（约 7.5k 字）。生僻字不在
  子集里也没关系——Typst 会按字体族列表逐字回退到系统字体。
- **改名**：子集不再叫 Noto Serif SC。一是避免和用户本机完整版重名（Typst 选中
  哪个不确定），二是避免让人误以为是完整字体，三是避开 Noto / Source / ZJU 商标。
- 保留 ``wght`` 变量轴，标题 ``weight: "bold"`` 才有真正的粗体。
- 许可：字体继续以 OFL 1.1 分发，``OFL.txt`` 与 ``FONT-NOTICE.md`` 随包。

用法::

    python tools/build_font_subset.py            # 下载源字体后生成
    python tools/build_font_subset.py --check    # 只校验产物与元数据
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
OUT_FONT = os.path.join(OUT_DIR, "NotesSerifSC-Subset.ttf")

SOURCE_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifsc/"
    "NotoSerifSC%5Bwght%5D.ttf"
)
SOURCE_SHA256 = "050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9"
SOURCE_SIZE = 25125512

NEW_FAMILY = "Notes Serif SC"
NEW_PS = "NotesSerifSC-Subset"

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


def download_source(target: str) -> None:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "zju-lecture-plugin/font"})
    with urllib.request.urlopen(request, timeout=180, context=_ssl_context()) as response:
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


def subset(source: str, output: str) -> None:
    from fontTools import subset as font_subset
    from fontTools.ttLib import TTFont

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

    rename(output)


def _set_name(table, name_id: int, value: str, platform_encodings=None) -> None:
    for record in table.names:
        if record.nameID != name_id:
            continue
        if platform_encodings and (record.platformID, record.platEncID) not in platform_encodings:
            continue
        try:
            record.string = value
        except Exception:  # noqa: BLE001
            pass


def rename(path: str) -> None:
    from fontTools.ttLib import TTFont

    font = TTFont(path)
    name = font["name"]
    _set_name(name, 1, NEW_FAMILY)
    _set_name(name, 16, NEW_FAMILY)
    _set_name(name, 4, NEW_FAMILY)
    _set_name(name, 6, NEW_PS)
    _set_name(name, 3, f"{NEW_PS};1.000")
    _set_name(name, 17, "Regular")
    _set_name(name, 21, NEW_FAMILY)
    _set_name(name, 22, "Regular")
    if 25 in {record.nameID for record in name.names}:
        _set_name(name, 25, NEW_PS)
    # 变量字体的 family 记录会被 fvar 的实例名引用，保持简单一致即可。
    font.save(path)
    font.close()


def copy_license() -> None:
    request = urllib.request.Request(
        "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifsc/OFL.txt",
        headers={"User-Agent": "zju-lecture-plugin/font"},
    )
    with urllib.request.urlopen(request, timeout=60, context=_ssl_context()) as response:
        text = response.read().decode("utf-8")
    if "SIL OPEN FONT LICENSE" not in text:
        raise SystemExit("OFL.txt 内容异常，拒绝写入。")
    with open(os.path.join(OUT_DIR, "OFL.txt"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)

    notice = f"""# 字体声明 — Notes Serif SC

`NotesSerifSC-Subset.ttf` 是 **Noto Serif SC** 的子集（subset），不是完整字体。

| 项 | 值 |
| :--- | :--- |
| 上游字体 | Noto Serif SC（可变字体，`wght` 200–900） |
| 上游版权 | Copyright 2012 Google Inc. All Rights Reserved.；字体内部 © 2017-2023 Adobe |
| 上游许可 | SIL Open Font License 1.1（见同目录 `OFL.txt`） |
| 修改 | 子集化（GB2312 + ASCII + 常用标点/数学符号）、关闭 hinting、**改名** |
| 本文件许可 | 仍为 SIL OFL 1.1（OFL 要求衍生字体沿用同一许可） |
| 覆盖范围 | 约 7.5k 个字符；生僻字不在本子集中，由 Typst 按字体族列表回退到系统字体 |

## 为什么改名

- 避免与用户本机安装的完整版 `Noto Serif SC` 同名——同名时 Typst 选哪个字体面不确定；
- 避免让人误以为拿到了完整字体；
- 避开 Noto / Source / ZJU 商标。

## 分发义务

- 分发本字体（含随插件打包、随 PDF 嵌入）时必须同时提供 `OFL.txt` 与本节版权声明。
- OFL 允许与软件捆绑分发，但**不得单独售卖字体本身**。
- 不要把本字体改回 `Noto Serif SC` 之类的上游名称。

## 重新生成

```bash
python tools/build_font_subset.py
```

脚本从 Google Fonts 固定路径下载源字体并按 SHA256 校验（`{SOURCE_SHA256}`），
所以产物可复现；源文件变更需要显式更新脚本里的哈希。
"""
    with open(os.path.join(OUT_DIR, "FONT-NOTICE.md"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(notice)


def check() -> int:
    problems = 0
    if not os.path.isfile(OUT_FONT):
        print("✗ 缺少 NotesSerifSC-Subset.ttf")
        return 1
    from fontTools.ttLib import TTFont

    font = TTFont(OUT_FONT)
    families = {record.toUnicode() for record in font["name"].names if record.nameID in (1, 16)}
    size_mb = os.path.getsize(OUT_FONT) / 1e6
    if NEW_FAMILY not in families:
        print(f"✗ 字体族名不是 {NEW_FAMILY}：{families}")
        problems += 1
    if "Noto" in " ".join(families):
        print(f"✗ 仍含 Noto 字样：{families}")
        problems += 1
    has_axes = "fvar" in font
    print(f"✓ {os.path.basename(OUT_FONT)}  {size_mb:.1f} MB  族名={sorted(families)}  变量轴={has_axes}")
    for required in ("OFL.txt", "FONT-NOTICE.md"):
        if not os.path.isfile(os.path.join(OUT_DIR, required)):
            print(f"✗ 缺少 {required}")
            problems += 1
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="", help="本地源字体路径（默认下载并校验）")
    parser.add_argument("--check", action="store_true", help="只校验产物")
    args = parser.parse_args()

    if args.check:
        return check()

    os.makedirs(OUT_DIR, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        if args.source:
            source = args.source
            digest = sha256_of(source)
            if digest != SOURCE_SHA256:
                print(f"✗ 源字体 SHA256 不符：{digest}", file=sys.stderr)
                print("  为确保产物可复现，请使用 Google Fonts 的 NotoSerifSC[wght].ttf。",
                      file=sys.stderr)
                return 2
        else:
            source = os.path.join(tmp, "NotoSerifSC-VF.ttf")
            print(f"下载源字体：{SOURCE_URL}")
            download_source(source)
            digest = sha256_of(source)
            if digest != SOURCE_SHA256:
                print(f"✗ 源字体 SHA256 不符：{digest}", file=sys.stderr)
                return 2

        print(f"源字体 {os.path.getsize(source)/1e6:.1f} MB，SHA256 {digest[:16]}…")
        print(f"子集字符数：{len(charset())}")
        subset(source, OUT_FONT)

    copy_license()
    print(f"\n写入 {OUT_FONT}（{os.path.getsize(OUT_FONT)/1e6:.1f} MB）")
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
