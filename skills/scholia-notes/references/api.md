# scholia API reference（基于 @preview/scholia:0.1.0 实测源码）

> 本文件是**事实性技术文档**（函数签名、参数取值、配色数值），由阅读上游源码整理而成，
> 不是上游文档的翻译或复制。上游包的作者、许可与仓库地址列在下方；
> 逐条归属见 [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。
> 本项目与上游包无隶属关系，未获其背书。
>
> **本文件里的数值是上游 0.1.0 的行为。** 本项目实际生效的排版数值（字体、字号、
> 版心、边注、封面）以 [`typography-spec.md`](typography-spec.md) 为准；vendored
> 副本已由 `tools/vendor_typst_packages.py` 打补丁，差异见
> [`../../../zju_lecture/typst-packages/VENDORED.md`](../../../zju_lecture/typst-packages/VENDORED.md)。

- 包：`@preview/scholia:0.1.0`，MIT，入口 `src/lib.typ`，最低 Typst 0.13.0
- 直接依赖：`@preview/marginalia:0.3.1`（右边栏）、`@preview/frame-it:2.0.0`（knot = figure）
- 仓库：https://github.com/Eryc123Y/scholia
- 源码文件：`src/colors.typ`（配色 + theme 状态）、`src/fonts.typ`、`src/visual.typ`、
  `src/theorems.typ`（knot）、`src/lib.typ`（voice / 教学装置 / 边注 / 封面 / 包装器）

## 1. 包装器 `scholia`

```typst
#let scholia(theme: "light", prose: "notes", paper: "a4", fonts: none, body)
```

| 选项 | 取值 | 效果 |
|---|---|---|
| `theme` | `"light"`（默认）/ `"dark"` | 换整套配色卡；dark 为深蓝灰 slate |
| `prose` | `"notes"`（默认）/ `"book"` | notes＝无首行缩进 + 段间距 0.95em；book＝首行缩进 1.2em + 段间距 0.7em |
| `paper` | `"a4"`（默认）/ `"us-letter"` / 任意 Typst paper 字符串 | 纸张 |
| `fonts` | dict，浅合并覆盖 `default-fonts` | 例：`(heading: ("Optima",))` |

包装器固定做的事：`set text(size: 11pt, lang: "en", fill: 主题 ink)`、`set par(justify: true)`、
`set heading(numbering: "1.1")`、一级标题重置 frame-it 计数器、页脚右侧页码、
marginalia 页边距（inner far 6mm/width 12mm，outer far 6mm/width 26mm）、启用 knot 样式。

**配色不能通过 `scholia.with(...)` 选项覆盖**，只有 light / dark 两张卡。但包导出了
`active` 这个 state，可以在包装器**之后**注入任意调色板，无需 vendor：

```typst
#show: scholia.with(theme: "light")
#show: use-palette        // 见 references/prelude.typ，内部就是 active.update(dict)
```

前提：新 dict 必须包含全部 11 个 role —— `dark` `bg` `ink` `muted` `hairline`
`thm` `def` `eg` `rule` `tag` `keyword`；`tint()` 依赖其中的 `dark` 与 `bg`。
本项目额外加了一个 `fillin`（填空线颜色，见 §2 的说明）。
要改配色见 `references/style.md`。

### 本项目覆盖的两个上游函数

| 函数 | 上游行为 | 本项目改为 | 为什么 |
| :--- | :--- | :--- | :--- |
| `fillin` | 底线用 `ink`（近黑） | 底线用 `fillin`（灰 `#8E97A3`） | 练习块里的填空线是**留给读者写**的地方；黑色会看起来像印刷内容，灰色一眼就知道该往哪写 |
| `accent` / `mark-key` / `warn` / `divider` / `aside` | 上游没有 | prelude 新增 | 淡彩配色下的行内强调手段 |

## 2. 配色角色（`colors.typ`）

| role | light | dark | 用途 |
|---|---|---|---|
| `bg` | white | `#141B27` | 页面底色 |
| `ink` | `#16202E` | `#E3E8F0` | 正文 |
| `muted` | `#6B7686` | `#8893A4` | 次要文字、页码 |
| `hairline` | `#D2D8E0` | `#2A3340` | `workspace` 横线 |
| `fillin` | `#8E97A3` | `#8E97A3` | 填空线（**本项目新增的第 12 个 role**，上游没有） |
| `thm` | `#2F5EA8` | `#74A6FF` | 定理族、章节规则线 |
| `def` | `#0F766E` | `#54C8B6` | 定义族、`remark` |
| `eg` | `#B45309` | `#E0A458` | example、`yourturn` |
| `rule` | `#2F5EA8` | `#74A6FF` | 标题下划线、封面横线 |
| `tag` | `#0F766E` | `#54C8B6` | `label-it` 小标签 |
| `keyword` | `#0F766E` | `#54C8B6` | `keyword` |

> 上表的 light 列是**上游包**的默认值。本项目在 `prelude.typ` 里用
> `#let soft-palette` 覆盖了浅色主题（`#33609B` / `#20705F` / `#8F6218` / `#6350A8`，
> 另有 `fillin`、`rule`、`hairline`、`muted`、`bg`），深色主题保持上游值。
> 权威色值与对比度见 `references/style.md` 与 `format-spec.md` §7。

`tint(p, c)`：light 下把强调色按 9% 混向底色，dark 下 16%——这是所有色块背景的算法。

## 3. knot（`theorems.typ`）

所有 knot 同属 `figure(kind: "frame")`，共用一个计数器，编号为 `章节号.序号`（`numbering("1.1", heading, n)`），
一级标题出现时计数器归零，即**按章节重新编号**。

补全列表（按颜色族）：

- 蓝 `thm`：`theorem` `lemma` `proposition` `corollary` `conjecture` `claim`
- 青 `def`：`definition` `axiom` `assumption` `notation`
- 琥珀 `eg`：`example`
- `remark`：无框，斜体青色行内块

参数形态（frame-it 内部签名：`title, tags, body, supplement, number, accent`）：

```typst
#theorem[正文]                      # 无标题
#theorem[标题][正文]                 # 常规
#theorem[标题][GSM 8.3, Thm 2.16][正文]  # 中间槽 = 标签(s)，用 label-it 渲染
```

标签与交叉引用用 Typst 原生机制：

```typst
#definition[特征值][…] <def:eig>
#theorem[重根情形][…] [如 @def:eig 所述，…]
```

`proof[正文]`：斜体 `Proof.` 起头，右侧 `h(1fr)` 后自动补一个主题色实心小方块（qed）。

## 4. voice 与教学装置（`lib.typ`）

| 函数 | 签名 | 渲染 |
|---|---|---|
| `note` | `note(body)` | 满宽可断块，左侧 `thm` 色 1.6pt 竖线 + 淡底色，sans 字体 0.92em |
| `whisper` | `whisper(body)` | 行内文本，`thm` 色，无底色 |
| `keyword` | `keyword(body)` | 行内粗体 `keyword` 色 |
| `block-head` | `block-head(body)` | 块级小标题，`thm` 色粗体 |
| `trigger` | `trigger(body)` | 块级，前缀 `Trigger.`（`def` 色粗体） |
| `fillin` | `fillin(width: 2.2cm)` | 宽 `width`、高 0.9em 的底线空 box |
| `TODO` | `TODO(hint)` | 行内 `[ fill in: hint ]`，sans 0.92em `eg` 色 |
| `yourturn` | `yourturn(body)` | 满宽块，左侧 `eg` 色 2pt 竖线 + 淡琥珀底，标题 `Your turn.` |
| `workspace` | `workspace(n: 3)` | n 条 `hairline` 细横线，每条间距 9pt |
| `sidenote` | `sidenote(body, symbol: none)` | 右边栏无编号边注（marginalia），0.82em muted |
| `recall` | `recall(body)` | `sidenote(body, symbol: [?])` |
| `cover` | `cover(title, subtitle:, author:, date:, kicker:)` | 独立页，`counter(page).update(1)` |
| `mark` | `mark(c, size: 6pt)` | 实心小方块（qed 用它） |
| `label-it` | `label-it(t)` | 8pt 粗体 sans `tag` 色小标签 |

`cover` 用对称页边距（x 2.5cm / top 2cm / bottom 2.3cm）、无页眉页脚、整体居中：
`kicker` 全大写加 3pt 字距 → 标题 30pt → 32% 宽 1pt 横线 → 副标题 → `1fr` → 作者 → 日期。

## 5. 字体角色（`fonts.typ`）

每个角色都是**回退列表**：好看的字体在前，Typst 内嵌字体垫底，所以缺字体只会告警不会崩。

> **下表是上游 0.1.0 的默认值，不是本项目实际生效的值。** 本项目的 vendored
> 副本（`zju_lecture/typst-packages/preview/scholia/0.1.0/`）由
> `tools/vendor_typst_packages.py` patch 过 `src/fonts.typ`：把 `Optima` /
> `Avenir Next` / `Menlo` / `Songti SC` 换成可再分发栈：`body`/`heading` 用
> STIX Two + 随包 `Notes Kai SC`；`sans`（方框标签、直觉块）用 `Noto Sans` /
> `Liberation Sans` / `DejaVu Sans`，中文仍回到 `Notes Kai SC`。实际生效的字体表
> 与许可列见 [`typography-spec.md`](typography-spec.md) §1，修改记录见
> `zju_lecture/typst-packages/VENDORED.md`。

| role | 上游默认列表 |
|---|---|
| `body` | `("STIX Two Text", "Libertinus Serif")` |
| `math` | `("STIX Two Math", "New Computer Modern Math")` |
| `heading` | `("Optima", "Libertinus Serif")` |
| `sans` | `("Avenir Next", "Libertinus Serif")` |
| `mono` | `("Menlo", "DejaVu Sans Mono")` |
| `cjk` | `("Songti SC",)` ← 只有 macOS 有 |

Typst 内嵌的四个字体（任何机器都有的基线）：Libertinus Serif、New Computer Modern(+Math)、DejaVu Sans Mono。
Typst 包不能打包字体，所以 STIX Two / Optima / Avenir Next 需要自行安装才有官方观感。

## 6. 已知限制（源码/README 明确写了）

1. 二级/三级标题是样式化块，不是真正的行内标题。
2. `fonts:` 覆盖只作用于 `body` / `math` / `heading`；`note` 声音、`sidenote`、knot 标签直接读
   `default-fonts`，**不跟随覆盖**——中文 fallback 想全覆盖，只能 vendor 包改 `src/fonts.typ`。
   本项目已经这样做了：vendored 副本的 `default-fonts` 已 patch 成可再分发栈，
   因此 `note` / `sidenote` / `label-it` 也跟随同一套字体（见 `typography-spec.md` §1）。
3. 配色只有 light/dark 两张固定卡，但可以用 `active.update(...)` 注入自定义调色板
   （必须放在 `#show: scholia.with(...)` 之后）。
4. `scholia` 导入了 marginalia 的 `note` 并改名为 `_note`，因此包内的 `note` 是 scholia 的直觉块，
   不是 marginalia 的边注——边注用 `sidenote`。