# 字体声明 — Notes Serif SC / Notes Kai SC

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
