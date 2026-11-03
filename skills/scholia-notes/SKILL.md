---
name: scholia-notes
description: |
  先用 Markdown 把内容写完整，再套 Typst scholia 模板（@preview/scholia:0.1.0）排版成
  STEM 填空式学习笔记：淡彩极简风格、克制用框、正文以黑白段落为主、强调靠加粗与淡色，
  配合定理框/定义框、填空线、证明骨架、边注主动回忆，并本地编译校验为 PDF/PNG。
  Use when the user mentions scholia, 填空笔记 / 学习笔记 / 复习提纲 / 主动回忆笔记,
  theorem box, fill-in blanks, active-recall study notes, or asks to author or compile a
  STEM notebook in Typst.
  Do NOT use for generic Typst typesetting or Chinese paper/thesis layout (use
  typst-author-chinese), for LaTeX papers, or when the user only asks what the template is.
descriptions:
  zh-Hans: "先用 Markdown 写内容，再套 scholia 模板排成淡彩极简的 STEM 填空笔记并编译校验。"
---

# Scholia Notes

> **先分清两份 PDF**：普通讲义（知识总结）的阅读版 PDF 由 `zju_write_note` 自动生成，
> 不需要本 Skill；本 Skill 只负责「可动手填写的复习笔记」这一种更重的产物。
> 用户只是要一份好读的讲义时，直接走 `zju_write_note`，不要启动这条填空链路。
> 两份 PDF 共用同一套配色、标记语义与版心参数（见格式规范），区别只在阅读版不挖空。

两段式工作流：**先用 Markdown 把内容和结构定死，再套模板排版**。
排版默认走淡彩极简——纸白、正文近黑、淡蓝淡青点睛、方框只在必要时出现。

> **格式规范（规范性文件）：[`references/format-spec.md`](references/format-spec.md)。**
> 语义对应关系、预算、禁止事项、数学写法、校验清单都在那里；
> 本文只讲怎么做事，细节冲突以规范为准。

> **正文是主角，框框是例外。** 一个框框唯一的正当理由是「这条内容需要被编号、
> 被后面的内容回指」。不需要被引用，就写成普通段落，用 `[强调]` / `[易错]` 标重点。
> 每节的框（所有类型合计）**不超过 2 个**；工具会逐节点名超预算的节。

> **本 skill 是非官方的第三方工作流说明**，与 `@preview/scholia` 包的作者、发行方无关，也未获其背书。
> 它使用该 MIT 授权的 Typst 包作为排版引擎。
> 许可与归属见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## Inputs to collect

| 输入 | 缺省行为 |
|---|---|
| 笔记主题与章节范围 | 用户没说就只做一节样例，不要虚构整套课程 |
| 语言 | 中文正文（Typst 0.15 自带回退，实测不用配 CJK 字体） |
| 风格 | 淡彩极简（默认）；用户明确要深色才切 `theme: "dark"` |
| 配色 | **按内容类型固定分色**，见下方色相表 |
| 强调强度 | 正文近黑 + 行内淡色加粗；不主动铺色块 |
| 交付物 | `notes.md`（内容底稿）+ `main.typ` + `out.pdf` |

## 配色：按内容类型固定分色

prelude 已内置四色体系，**照着用，不要另挑颜色**：

| 内容类型 | 色相 | 覆盖 |
|---|---|---|
| 结论 / 推理 | 蓝 `#33609B` | theorem lemma proposition corollary · `proof` · qed · 回指 |
| 定义 / 术语 | 青绿 `#20705F` | definition axiom assumption notation · `remark` · `mark-key` · `label-it` |
| 例子 / 练习 | 琥珀 `#8F6218` | `example` · `yourturn` · `TODO` · `workspace` |
| 易错 / 陷阱 | 紫 `#6350A8` | `#warn[…]` |
| 次要信息 | 灰 `#6F7683` | 页码 · 边注 · `aside` |
| 正文 | 近黑 `#1A1A1C` | 普通段落（主体） |

四个强调色的对比度极差 **1.11**，视觉等权，所以看起来是一套配色而不是一主两辅。
分组依据是「推理—定义—应用」的内容链条，色相全篇固定，读者才能靠颜色建立预期。
要换整套色相时保持等权（极差 ≤ 1.2）且每个 ≥ 4.5:1 —— 详见 `references/style.md`。

## Procedure

### 第 0 步：先判断有没有现成的通路

**在 dsh / MCP 宿主里（`dsh-zju-lecture-note` 插件已内置本 skill）**，两段式工作流是**工具化**的，
不要手写 Typst。如果看不到 `zju_build_study_notes`，说明插件里的「填空式学习笔记」模块
处于关闭状态（默认关闭）：要么让用户在设置里打开，要么按下面的手动流程走，不要假装工具存在。

| 步骤 | 工具 | 做什么 |
|---|---|---|
| 1 | `zju_build_study_notes(mode="draft", note_path=…)` | 讲义 → 填空底稿 `*-填空底稿.md`（标题层级映射、标记位插入、LaTeX 数学改写为 Typst 数学） |
| 2 | 人工/Agent 填底稿 | 把标记位补成真正的定义、定理、练习；**正文写成普通段落，框只给会被引用的那几条** |
| 3 | `zju_build_study_notes(mode="compile", draft_path=…)` | 底稿 → `main.typ` + `prelude.typ` → `out.pdf` + 逐页 `page-N.png` |

工具只做**搬运与排版**：哪些是定理、哪里该挖空，是内容判断，仍由你（Agent）完成。
工具会把「无法机械转换的数学」「超出视觉预算的方框」「方框 : 正文段落比值」
「编译错误」原样报出来，别自行吞掉。

**格式规范（规范性文件）在 [`references/format-spec.md`](references/format-spec.md)** ——
语义对应关系、预算、禁止事项、校验清单都在那里。

下面的手动流程适用于**没有装这个插件**的环境（纯 Typst、Claude Code、Cursor 等），
以及工具报出「无法机械转换」需要手工兜底的场合。

### 第一阶段：Markdown 定内容

1. 先写 `notes.md`，把这一份笔记的**全部内容与层级**用纯 Markdown 写完，不碰任何 Typst 语法。
   结构用约定标记（不是最终排版，是「意图声明」）：

   ```markdown
   # 封面
   - title: 课程名 第 n 讲 主题
   - author: 名字
   - date: 2026-11-02

   ## 章节标题
   普通段落，用来先讲清楚。整份笔记的主体都是这种黑字段落。

   [直觉] 这段是人话解释，读者读一遍就懂。

   [定义] 术语 —— 一句话说清对象，关键处留空：____
   [定理] 结论正文。@def:xxx
   [证明] (i) … (ii) … [缺口: 关键那一步]
   [例] 可模仿的完整示例。
   [练习] 留给用户自己重做。____ ____ ____
   [边注] 一个主动回忆问题。
   [强调] 需要淡色点睛的句子，登记在这里。
   ```

   原因：内容与排版分离后，公式、层级、留白位置都能一次审到位；
   直接写 Typst 会在版式调试中反复改内容，返工成本高（eval 实证：先写 Markdown 的那轮
   2 轮编译通过，写满 Typst 才编译的那轮 6 轮、4 个硬错误）。

   **底稿里不要写 Typst 语法**（`#note[…]`、`= 标题`、颜色、字号、手写编号）：
   底稿要保持「人能读、LLM 能改」的纯 Markdown。完整约定见
   [`references/format-spec.md`](references/format-spec.md)。

2. 审一遍底稿再进第二阶段：公式、章节顺序、哪句要强调、**哪几条真的需要被回指**。
   Typst 数学的坑（`a_(ij)`、多字母标识符、`\overline`）**不用你手工改** ——
   工具会统一把 LaTeX 数学转成 Typst 数学，转不动的会点名报出来（见 §4 的工具路径）。

3. 复制 `references/prelude.typ` 到项目目录，然后写 `main.typ`：

   ```typst
   #import "prelude.typ": *
   #show: scholia.with(theme: "light", prose: "notes")
   #show: use-palette
   ```

   原因：prelude 提供淡彩 palette 与 `accent` / `mark-key` / `divider` / `aside`；
   `use-palette` 必须排在 `scholia.with(...)` **之后**，否则会被包装器重置回内置 light。
   必须 `#import` 不能 `#include`（见失败处理）。

   > 本 skill 目录里的 `references/prelude.typ` 是**生成副本**，单一来源在
   > `zju_lecture/prelude.typ`；由 `tools/sync_skill_assets.py` 同步，测试会校验两者逐字节一致。

4. 按 Markdown 骨架逐条映射（**规范见 [`references/format-spec.md`](references/format-spec.md)**，
   速查表见 [`references/mapping.md`](references/mapping.md)），并遵守视觉预算：

   | | 每节上限 | 说明 |
   |---|---|---|
   | 正文段落 | 不限 | 近黑，是主体 |
   | `accent` / `mark-key` 行内强调 | 2～3 处 | **首选**的强调手段 |
   | `divider` | 1～2 条 | 段落切分 |
   | `note`（带底色块） | 1 | 整节直觉 |
   | knot 方框（**所有类型合计**） | **≤ 2** | 含 definition/theorem/example 等，仅为编号回指而设 |
   | `yourturn` 练习块 | 1 | 需要留白给用户写 |
   | `recall` / `sidenote` 边注 | 1～2 | 不占版面，最省空间 |

   原因：方框是这套模板最重的视觉元素，堆多了整页就糊；正文保持黑白，
   强调用行内淡色加粗，视觉负担小一个数量级。knot 只为「可编号、可回指」而存在。
   口径以 `references/style.md` 第 3 节为准。

   **中文正文额外加这几行**（放在 `#show: use-palette` 之后）：

   ```typst
   #set text(lang: "zh")
   #set par(
     justify: false,
     leading: 0.72em,
     first-line-indent: 0pt,
     spacing: 0.95em,
   )
   #show math.equation.where(block: true): set block(above: 1.6em, below: 1.6em)
   ```

   原因：scholia 包装器写死 `lang: "en"` 且 `justify: true`；
   前者影响断行规则，后者会让两端对齐把中文字距拉得很松（实测 `justify: false` 才是关键）。
   `spacing` 略大于 `leading`，段落看得出来但不夸张。
   块级公式的上下间距**必须显式给** —— 它一旦跟着 `par.spacing` 走，
   公式就会压到下一段文字上（实测重叠）。
   完整口径见 [`references/format-spec.md`](references/format-spec.md) §1.2。

5. 编译并肉眼验版（**两道关，缺一不可**）：

   ```powershell
   typst compile main.typ out.pdf
   typst compile main.typ "page-{p}.png"     # 逐页看排版
   ```

   第一道关：`error:` 一条都不能留。
   第二道关：**必须看 PNG**。knot 的内容块数量错位时**不会报错**——
   `#theorem[标题][正文]` 误写成 `#theorem[标题][正文][多余内容]` 时，
   第二个块会被当成标签槽渲染成小字标签，退出码仍是 0。
   所以 grep `error:` 不能替代肉眼验版。
   字体告警无害，见 `references/troubleshooting.md`。

6. 交付 `notes.md` + `main.typ` + `out.pdf`，并说明用了哪套 palette、方框用了多少个。

## Markdown → Typst 映射表

**完整语义对应表在 [`references/format-spec.md`](references/format-spec.md)**（规范性文件），
速查版在 [`references/mapping.md`](references/mapping.md)。

| notes.md 标记 | Typst 写法 | 重量 |
|---|---|---|
| `# 封面` 段 | `#cover("标题", subtitle: …, author: …, date: …, kicker: …)` | — |
| `## 章节` | `= 章节` | — |
| `### 小节` | `== 小节`（**不要手写编号**，包装器自动编号） | — |
| **普通段落** | **直接写 —— 正文的主体** | **无** |
| `[直觉]` | `#note[…]` | 带底色，每节≤1 |
| `[定义]` | `#definition[术语][…] <def:x>` | 方框（≤2/节） |
| `[定理]/[引理]/[推论]` | `#theorem[标题][来源标签][…] <thm:x>` | 方框（≤2/节） |
| `[证明]` | `#proof[… #TODO[缺口] …]` | 无框 + qed |
| `[例]` | `#example[标题][…]` | 方框（≤2/节） |
| `[练习]` | `#yourturn[…] #workspace(n: 3)` | 方框 + 留白 |
| `[边注]` | `#recall[…]` | 右栏，最省空间 |
| `[易错]` | `#warn[…]` | 行内紫字，不占预算 |
| `[强调]` | `#accent([句子])` / `#mark-key[术语]` | **行内，最轻** |
| `____` 填空 | `#fillin(width: 2.2cm)`（灰色；**练习块里不画**，那里已有书写横线） | — |
| `@def:xxx` 回指 | 原生 `@def:xxx`，label 写在 knot 后 | — |

## 内容出处：自己的话 + 可核对的来源

模板只管排版，**内容归属是你要负责的事**：

- 定理、公式、结论可以用**自己的话复述**事实，但**必须注明出处**（书名/讲义/课程号），
  例如「（Smith, *Linear Algebra*, 3rd ed., Thm 4.2）」。
- **习题、习题答案、教材例题原文不要整段照搬**；改成自己编的等价题，或注明出处并只引用结论。
- 讲义的**课堂截图、PPT 画面**属于授课教师与学校的材料，不要原样嵌进公开分发的笔记；
  需要时用自己重画的示意图替代。
- 定理的**表述本身**不是著作权对象（事实与思路不受保护），但**特定表达**受保护；
  复述时用自己的句子写。

## Output contract

- `notes.md`：内容底稿，Markdown，结构标记完整，用户可独立阅读和修改。
- `main.typ` + `prelude.typ`：可独立编译，顶部三行固定为 import + `scholia.with` + `use-palette`。
- `out.pdf`：编译产物；需要确认效果时附 `page-N.png`。
- 编译输出里 `warning: unknown font family` 可忽略，`error:` 一条都不能留。

## Failure handling

- `#include "prelude.typ"` 后报 `unknown variable: accent`：prelude 必须用 `#import "prelude.typ": *`，
  include 拿不到作用域。
- 注入的配色没生效：`#show: use-palette` 必须写在 `#show: scholia.with(...)` 之后。
- 在 prelude 的 `accent(裸中文, tone: …)` 报 `unknown variable`：圆括号是 code 模式，裸中文被当变量名，
  用方括号 `#accent[中文]`。
- 标题渲染成 `1.1 1.1 小节`：包装器已自动编号，正文不要手写编号。
- **渲染出来位置不对但不报错**：knot 的内容块是位置参数，
  `[a]`=标题、`[a][b]`=标题+正文、`[a][b][c]`=标题+标签+正文。
  写了三个块却以为是「标题+正文」，第二个块会被渲染成小字标签——
  **退出码是 0，grep `error:` 抓不到**，只能靠看 PNG 发现。
- 公式报 `unknown variable` 或渲染出字面量：`$a_(ij)$`、`$rank(A)$`、`$\prod_…$`、`$\overline{A}$`
  在 Typst 里全是错的；正确写法见 `references/troubleshooting.md`。这类错应在 Markdown 阶段就改掉。
- `sidenote` 的 `symbol` 必须圆括号：`#sidenote([正文], symbol: [!])`，方括号写法直接报 `unexpected argument`。
- 首次编译卡住无输出（包注册表不通）：重试一次，仍不行就把依赖名报给用户，别空等。
- 用户要的是中文论文/长文排版而非填空笔记：这个 skill 不适用，转 `typst-author-chinese`。

## Examples

**输入**：「用 scholia 做一份线性代数期中复习提纲，要能填空自测。」

**输出**：
1. `notes.md`：5 个章节（行列式／线性方程组／向量空间／特征值／自测清单），
   每条按 `[直觉] [定义] [定理] [证明] [例] [练习] [边注]` 标记，公式写成 LaTeX。
2. `prelude.typ` 复制到项目目录；`main.typ` 顶部三行 setup，正文以近黑段落为主，
   强调用 `#mark-key[特征值]` 这类行内淡色，**全篇只有 6 个框**（每个都是后面会被引用的那几条）。
3. `out.pdf` 编译通过（exit 0）；逐页 PNG 看一遍——框的内容块错位不报错，只有看图才发现。

## Windows (win32) platform notes

```powershell
typst --version                 # 需要 ≥ 0.13.0
typst compile main.typ out.pdf
typst compile main.typ "page-{p}.png"
typst compile --pages 1-2 main.typ "page-{p}.png"
typst fonts                     # 看本机可用字体名
```

- 用 Read/Write 工具写 `.md`/`.typ`，不要用 `Set-Content`（PowerShell 5.1 默认 ANSI 会破坏 UTF-8 中文）。
- 本机缺 `STIX Two` / `Optima` / `Avenir Next` / `Songti SC`，编译会刷一串
  `warning: unknown font family`。**无害**，Typst 自动回退，中文照样出字。
- 想要接近官方的字体观感就装 STIX Two（免费/OFL）。
- 想指定中文字形：`#show: scholia.with(fonts: (cjk: ("Noto Serif SC",), heading: ("Microsoft YaHei",)))`，
  但它进不了 `note`/`sidenote`/`label-it`（这三个直接读包内 default-fonts）。

### 字体与分发（对外分享 PDF 前必读）

Typst 编译 PDF 时会**内嵌并子集化**用到的字体。上游 `scholia` 的默认字体表里
`Optima` / `Avenir Next` / `Menlo` / `Songti SC` 都是**商业专有字体**，
一旦本机装了并被用上，这些字体的子集就会进入 PDF；把该 PDF 再分发出去，
就属于字体分发，多数商业字体 EULA 明确限制。

| 场景 | 建议 |
|---|---|
| 自己复习、存档 | 直接用默认字体，回退到 Typst 内嵌的 Libertinus 即可 |
| 要把 PDF 发给别人 / 公开分发 | 把 `body` / `math` / `heading` / `sans` 覆盖成 **STIX Two（OFL）** 或 Typst 内嵌字体，确保 PDF 里只有可再分发的字体 |

```typst
#show: scholia.with(
  theme: "light",
  fonts: (
    body: ("STIX Two Text", "Libertinus Serif"),
    math: ("STIX Two Math", "New Computer Modern Math"),
    heading: ("STIX Two Text", "Libertinus Serif"),
    sans: ("STIX Two Text", "Libertinus Serif"),
  ),
)
```

> 注意 `fonts:` 覆盖**进不了** `note` / `sidenote` / `label-it`（这三个直接读包内 default-fonts），
> 所以只覆盖 `body` 并不彻底；要彻底可控就 vendor 包改 `src/fonts.typ`（保留上游 MIT 声明，见
> `THIRD_PARTY_NOTICES.md`）。

## 许可与致谢

- 本 skill（工作流说明、配色方案、`prelude.typ` 扩展、`mapping` / `style` / `troubleshooting` 文档）
  以 **MIT** 授权发布，见 [`LICENSE`](LICENSE)。
- 排版引擎 [`@preview/scholia`](https://typst.app/universe/package/scholia)（MIT © Eric Yang）
  及其依赖 `@preview/frame-it`（MIT）、`@preview/marginalia`（UNLICENSE）均为宽松授权，
  在编译期由 Typst 包注册表拉取，**未随本仓库分发**。
- 逐条归属见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
