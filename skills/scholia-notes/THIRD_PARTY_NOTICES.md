# Third-party notices — `scholia-notes`

本目录（`skills/scholia-notes/`）是一套**独立的第三方工作流说明**，随 `dsh-zju-lecture-note`
插件一同开源。它**不是** `@preview/scholia` 包的官方作品，也未获其作者背书。

## 1. 本目录的原创部分（MIT）

| 文件 | 内容 |
| :--- | :--- |
| `SKILL.md` | 两段式工作流 SOP、配色分色方案、视觉预算、内容出处规则 |
| `LICENSE` | 本目录自身的 MIT 许可（Copyright (c) 2026 chenqianyu486） |
| `references/prelude.typ` | **生成副本**，单一来源见 `zju_lecture/prelude.typ`（见 §4） |
| `references/starter.typ` | 起步模板 |
| `references/api.md` | 基于上游源码实测整理的 API 参考（事实性技术文档） |
| `references/mapping.md` | Markdown 底稿 → Typst 的映射表 |
| `references/style.md` | 淡彩极简风格指南、WCAG 对比度量化口径 |
| `references/troubleshooting.md` | 排错记录（Typst 数学模式、字体、平台差异） |

`references/prelude.typ` 中新增的 `accent` / `mark-key` / `warn` / `divider` / `aside`
五个助手与 `soft-palette` 配色表均为本项目原创，**未复制上游 `src/` 中的任何实现**。

## 2. 随包分发的 Typst 包（vendored，v2.1.0 起）

这些包的源码**已随本仓库分发**在 `zju_lecture/typst-packages/`，编译时通过
`typst compile --package-path` 解析，因此离线也能编译填空笔记。

| 包 | 版本 | 许可 | 版权人 | 用途 |
| :--- | :--- | :--- | :--- | :--- |
| [`@preview/scholia`](https://typst.app/universe/package/scholia) | 0.1.0 | MIT | Eric Yang（杨星宇） | 填空式学习笔记模板（knot / note / 边注 / 封面） |
| [`@preview/frame-it`](https://typst.app/universe/package/frame-it) | 2.0.0 | MIT | Marc Thieme | scholia 的 knot 底层（figure + 原生 label 交叉引用） |
| [`@preview/marginalia`](https://typst.app/universe/package/marginalia) | 0.3.1 | UNLICENSE | 公有领域 | scholia 的右边栏边注 |
| [`@preview/theoretic`](https://typst.app/universe/package/theoretic) | 0.3.1 | UNLICENSE | 公有领域 | noteworthy 的定理底层 |
| [`@preview/showybox`](https://typst.app/universe/package/showybox) | 2.0.4 | MIT | Pablo González Calderón | noteworthy 的方框底层 |
| [`@preview/noteworthy`](https://typst.app/universe/package/noteworthy) | 0.4.0 | MIT | Tarun Kumar Jana | 证明 / 注记装置 |

上游 `scholia` 的作者声明其实现是受 `loom-notes`（XeLaTeX，MIT © Polaris）**设计启发**的独立重写，
未复用其源码；`loom-notes` 亦未随本仓库分发。

除填空笔记直接使用这些包外，本插件的**阅读版讲义**模板（`zju_lecture/handout_prelude.typ`）
在**视觉与信息结构**上参照 scholia 的浅色 notes 主题（配色角色、命题 / 证明 / 边注装置、
右侧 Tufte 边注、三线表）。该模板是本项目独立编写的 Typst 代码，**不 import 上游包、
不复制其 `src/`**；色值本身见 §3.1。

> **MIT 的硬性义务已履行**：每个 MIT 包都随目录保留了上游 `LICENSE` 与版权声明；
> Unlicense 包保留 `UNLICENSE` 文本。修改范围仅限删除 README 与模板示例，代码与
> `typst.toml` 保持上游原样。分发本插件（npm 包 / MCode zip）时必须把
> `zju_lecture/typst-packages/` 一并带上，否则等于分发了代码却不带许可。

本插件与 `@preview/scholia` 的作者没有隶属关系，也未获其背书；「scholia」仅用于指代所依赖的包。

## 3. 字体（不随本仓库分发，但影响产物的可再分发性）

Typst 编译 PDF 时会内嵌并子集化用到的字体。上游 `scholia` 的默认字体表引用了
`Optima`、`Avenir Next`、`Menlo`、`Songti SC`——**均为商业专有字体**；
`STIX Two` 为 SIL OFL，可自由再分发；`Libertinus Serif`、`New Computer Modern`、
`DejaVu Sans Mono` 由 Typst 运行时内嵌。

本项目在 `SKILL.md` 中明确要求：**对外分发 PDF 前**把字体覆盖成 `STIX Two` 或 Typst 内嵌字体，
避免把商业字体子集带进可公开分发的文件。阅读版讲义（`zju_lecture/handout_prelude.typ`）
**默认就用可再分发的字体栈**（STIX Two → 内嵌 Libertinus，中文优先随包 `Notes Serif SC`），
不依赖任何商业字体。

### 3.0 随包字体 `Notes Serif SC`（v2.1.0 起）

| 项 | 值 |
| :--- | :--- |
| 文件 | `zju_lecture/fonts/NotesSerifSC-Subset.ttf` |
| 上游 | Noto Serif SC（SIL OFL 1.1，无 Reserved Font Name） |
| 版权 | Copyright 2012 Google Inc.；字体内部 © 2017-2023 Adobe |
| 修改 | GB2312 + ASCII + 常用标点/数学符号子集，关闭 hinting，**改名** |
| 许可文件 | `zju_lecture/fonts/OFL.txt` + `FONT-NOTICE.md`（必须随包分发） |

OFL 允许子集化与再分发，但要求：衍生字体继续以 OFL 分发、随附许可与版权声明、
不得单独售卖字体。改名是为了避免与本机完整版 `Noto Serif SC` 重名（Typst 选中哪个字体面
不确定），并避开 Noto / Source / ZJU 商标。

其余情况：本仓库**不分发任何商业字体**，只写字体名；缺字时 Typst 回退到内嵌字体族与系统字体。
若 PDF 里出现了 `SimSun` / `Microsoft YaHei` 等系统商业字体，那是生僻字回退的结果，
这类 PDF 不宜对外分发。

## 3.1 配色

浅色主题（`soft-palette`：`#FDFDFB` / `#1A1A1C` / `#33609B` / `#20705F` / `#8F6218` /
`#6350A8` / `#6F7683` / `#8E97A3` / `#93A6C4` / `#DBDFE6`）是本**项目自己的定义**，
不来自上游；深色主题（slate）由上游 `scholia` 提供。配色不改变本文件任何归属结论。

## 4. `prelude.typ` 的单一来源

`zju_lecture/prelude.typ` 是**唯一权威副本**，随 Python 包分发，供 `zju_build_study_notes`
在编译时写入项目目录。本目录下的 `references/prelude.typ` 是由
`tools/sync_skill_assets.py` 生成的**副本**，测试 `tests/test_study_notes.py` 会校验两者逐字节一致。
改配色请改权威副本，然后重新同步。

## 5. 声明

- 本目录不使用任何上游的 logo、截图或品牌素材。
- 「scholia」一词仅用于**指代**所依赖的 Typst 包，属指示性使用。
