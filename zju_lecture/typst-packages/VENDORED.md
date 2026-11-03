# Vendored Typst packages

本目录是**随包分发的第三方代码**，不是本项目原创。编译时通过
`typst compile --package-path <本目录>` 解析 `@preview/…`，因此填空笔记
链路不需要联网。

| 包 | 版本 | 许可 | 许可文件 | 文件数 |
| :--- | :--- | :--- | :--- | ---: |
| `@preview/scholia` | 0.1.0 | MIT | `LICENSE` | 7 |
| `@preview/frame-it` | 2.0.0 | MIT | `LICENSE` | 13 |
| `@preview/marginalia` | 0.3.1 | Unlicense | `UNLICENSE` | 3 |
| `@preview/theoretic` | 0.3.1 | Unlicense | `UNLICENSE` | 11 |
| `@preview/showybox` | 2.0.4 | MIT | `LICENSE` | 8 |
| `@preview/noteworthy` | 0.4.0 | MIT | `LICENSE` | 3 |

## 来源与修改

- 来源：<https://github.com/typst/packages>（Typst Universe registry 的公开仓库），
  逐个包按 `packages/preview/<name>/<version>/` 取用。
- 删除：`README.md` / `README.typ` / `template/` / `tests/` / `examples/` / `docs/`。
- frame-it 的 `README.md` 有 3.8MB（示例图），删除它同时避免分发来源不明的素材。
- **修改**：`@preview/scholia` 0.1.0 打了以下补丁（由
  `tools/vendor_typst_packages.py` 重放，重新 vendor 时会自动应用）：

| 文件 | 修改 |
| :--- | :--- |
| `src/fonts.typ` | 字体表改为可再分发栈：STIX Two / Libertinus / 随包 Notes Kai SC、Notes Serif SC / Noto / Source Han；移除 Optima / Avenir Next / Menlo / Songti SC |
| `src/lib.typ` | 二级/三级标题字号统一为 12.5pt / 11.5pt；边注段距补 0.4em |

  除上述补丁外，其余代码、`typst.toml` 与许可文件保持上游原样。

## 许可

MIT 包（scholia / frame-it / showybox / noteworthy）要求保留版权声明与许可全文；
本目录逐个包保留了 `LICENSE`。Unlicense 包（marginalia / theoretic）保留
`UNLICENSE` 文本。这些文件**必须随 npm 包与 MCode 包一起分发**，
否则等于分发了代码却不带许可。

逐条归属见仓库根目录 `ATTRIBUTION.md` 与 `skills/scholia-notes/THIRD_PARTY_NOTICES.md`。
