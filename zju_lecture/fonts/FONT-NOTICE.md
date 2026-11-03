# 字体声明 — Notes Serif SC

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

脚本从 Google Fonts 固定路径下载源字体并按 SHA256 校验（`050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9`），
所以产物可复现；源文件变更需要显式更新脚本里的哈希。
