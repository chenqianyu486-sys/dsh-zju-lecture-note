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

> **口径**：本 Skill 产出的是**基于 Typst scholia 模板排版的填空式学习笔记**；
> 配色与段落规范由本项目定义，见 [`references/typography-spec.md`](references/typography-spec.md)。
> **先分清两份 PDF**：普通讲义的阅读版 PDF 由 `zju_write_note` 自动生成，不需要本 Skill；
> 本 Skill 只负责「可动手填写的复习笔记」。用户只要一份好读的讲义时直接走 `zju_write_note`。
> 两份 PDF 共用同一套配色、标记语义与版心参数，区别只在阅读版不挖空。

两段式工作流：**先用 Markdown 把内容和结构定死，再套模板排版**。
排版默认淡彩极简——纸白、正文近黑、淡蓝淡青点睛、方框只在必要时出现。

> **格式规范（规范性文件）：[`references/format-spec.md`](references/format-spec.md)。**
> 语义对应、预算、禁止事项、数学写法、校验清单都在那里；本文只讲怎么做事，细节冲突以规范为准。
> **正文是主角，框框是例外**：框唯一的正当理由是「需要被编号、被回指」；每节框合计 **≤ 2**，
> 工具会逐节点名超预算的节。不需要被引用就写普通段落，用 `[强调]` / `[易错]` 标重点。
> 本 skill 是**非官方**的第三方工作流说明，与 `@preview/scholia` 的作者、发行方无关，也**未获其背书**；
> 许可与归属见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## Inputs to collect

| 输入 | 缺省行为 |
|---|---|
| 笔记主题与章节范围 | 用户没说就只做一节样例，不要虚构整套课程 |
| 语言 | 中文正文（Typst 0.15 自带回退，实测不用配 CJK 字体） |
| 风格 | 淡彩极简（默认）；用户明确要深色才切 `theme: "dark"` |
| 配色 | **按内容类型固定分色**，见下 |
| 强调强度 | 正文近黑 + 行内淡色加粗；不主动铺色块 |
| 交付物 | `notes.md`（内容底稿）+ `main.typ` + `out.pdf` |

## 配色：按内容类型固定分色

prelude 已内置四色体系，**照着用，不要另挑颜色**：结论 / 推理蓝、定义 / 术语青绿、例子 / 练习琥珀、
易错 / 陷阱紫、次要信息灰、正文近黑。色值、等权（极差 ≤ 1.2）与对比度 ≥ 4.5:1 的量化口径见
[`references/typography-spec.md`](references/typography-spec.md) §7 与 [`references/style.md`](references/style.md)。

## Procedure

### 第 0 步：先判断有没有现成的通路

**在 dsh / MCP 宿主里（插件已内置本 skill）**，两段式工作流是**工具化**的，不要手写 Typst。
看不到 `zju_build_study_notes` 说明「填空式学习笔记」模块关闭（默认关闭）：让用户在设置里打开，
或按下面的手动流程走，不要假装工具存在。

| 步骤 | 工具 | 做什么 |
|---|---|---|
| 1 | `zju_build_study_notes(mode="draft", note_path=…)` | 讲义 → 填空底稿 `*-填空底稿.md`（标题层级映射、正文原样搬运；**公式保持 LaTeX、表格保持 Markdown**，不写 Typst 语法，也**不逐节塞空占位**） |
| 2 | 人工/Agent 填底稿 | 按内容补 `[直觉]`/`[练习]`/`[边注]`（不需要就别加）、该挖空处写 `____`；**不要重写全文**，也别把公式改成 Typst |
| 3 | `zju_build_study_notes(mode="patch", draft_path=…, edits=[{old,new}, …])` | 把第 2 步全部改动**一次**写回（每处 `old` 必须唯一命中，命中结果逐条报出）。**不要一处一处调用编辑工具** |
| 4 | `zju_build_study_notes(mode="compile", draft_path=…)` | 底稿 → `main.typ` + `prelude.typ` → `out.pdf` + 逐页 `page-N.png`（PDF 同时落在底稿同目录） |

工具只做**搬运与排版**：哪些是定理、哪里该挖空是内容判断，仍由你完成。LaTeX → Typst 转换**只在 compile
做一次**：底稿保持 LaTeX，反过来把底稿改写成 Typst 会被二次转换拆坏。无法机械转换的数学、超预算方框、
方框 : 正文比值、编译错误都会原样报出来，别自行吞掉。

**`mode=patch` 的用法**：读完底稿后把十几处 `{old, new}` 攒成一个数组一次提交：

```json
{"mode": "patch", "draft_path": "…-填空底稿.md",
 "edits": [
   {"old": "**总电流连续**", "new": "**总电流____**"},
   {"old": "这就是电磁波的直接来源。", "new": "…。\n\n[边注] …"}
 ]}
```

`old` 在底稿里必须**恰好出现一次**（重复时加长上下文，或加 `"all": true`）；没命中的逐条点名，已命中的照常写回。
格式规范在 [`references/format-spec.md`](references/format-spec.md)。下面的手动流程适用于**没装插件**的环境
（纯 Typst、Claude Code、Cursor 等）以及工具报「无法机械转换」需要手工兜底的场合。

### 第一阶段：Markdown 定内容

1. 先写 `notes.md`，把**全部内容与层级**用纯 Markdown 写完，不碰任何 Typst 语法。
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

   内容与排版分离才能一次审到位；直接写 Typst 会在版式调试中反复改内容。**底稿里不要写 Typst 语法**
   （`#note[…]`、`= 标题`、颜色、字号、手写编号），保持「人能读、LLM 能改」；完整约定见
   [`references/format-spec.md`](references/format-spec.md)。

2. 审一遍底稿再进第二阶段：公式、章节顺序、哪句要强调、**哪几条真的需要被回指**。
   Typst 数学的坑不用你手工改——工具统一把 LaTeX 转成 Typst，转不动的会点名（见第 0 步工具路径）。

3. 复制 `references/prelude.typ` 到项目目录，然后写 `main.typ`：

   ```typst
   #import "prelude.typ": *
   #show: scholia.with(theme: "light", prose: "notes")
   #show: use-palette
   ```

   `use-palette` 必须排在 `scholia.with(...)` **之后**（否则被包装器重置回内置 light）；必须 `#import` 不能
   `#include`（见失败处理）。目录里的 `references/prelude.typ` 是**生成副本**，单一来源在 `zju_lecture/prelude.typ`，
   由 `tools/sync_skill_assets.py` 同步，不要手改副本。

4. 按骨架逐条映射（规范见 [`references/format-spec.md`](references/format-spec.md)，速查见
   [`references/mapping.md`](references/mapping.md)）。视觉预算：knot 方框每节合计 **≤ 2**、直觉 / 练习各 1、
   边注 1–2、行内强调 2–3、正文段落不限；口径以 `references/format-spec.md` §2.2 为准。

   **中文正文额外加这两行**（放在 `#show: use-palette` 之后）：

   ```typst
   #set text(lang: "zh")
   #set par(justify: false)
   ```

   包装器写死 `lang: "en"` 且 `justify: true`，后者会把中文字距拉松；行距 / 段距 / 缩进 / 公式间距等**数值**见
   [`references/typography-spec.md`](references/typography-spec.md) §3，不要在这里重复。

5. 编译并肉眼验版（**两道关，缺一不可**）：

   ```powershell
   typst compile main.typ out.pdf
   typst compile main.typ "page-{p}.png"     # 逐页看排版
   ```

   第一道关：`error:` 一条都不能留。第二道关：**必须看 PNG**——knot 内容块数量错位时不报错（见失败处理）。
   字体告警无害，见 `references/troubleshooting.md`。

6. 交付 `notes.md` + `main.typ` + `out.pdf`，并说明用了哪套 palette、方框用了多少个。

## Markdown → Typst 映射

完整语义对应表在 [`references/format-spec.md`](references/format-spec.md)（规范性文件），
速查版在 [`references/mapping.md`](references/mapping.md)。

> **框与证明是「块」，不是「一行」**：从标记行开始一直排到下一个标记、标题或整行粗体的伪标题；
> 块里空行是段落分隔，`$$…$$`、列表、表格都留在装置里。`[证明]` 的 qed 排在**块内最后一行**——
> 证明要写到最后一段，不要把结论另起一段写在标记外面。`[直觉]` / `[练习]` / `[边注]` / `[强调]` 只吃标记行那一句。
> 完整规则见 [`references/format-spec.md`](references/format-spec.md) §2.4。

## 内容出处：自己的话 + 可核对的来源

- 定理、公式、结论可以用**自己的话复述**事实，但**必须注明出处**（书名/讲义/课程号）。
- **习题、习题答案、教材例题原文不要整段照搬**；改成自己编的等价题，或注明出处并只引用结论。
- 课堂截图、PPT 画面属授课教师与学校的材料，不要原样嵌进公开分发的笔记；需要时用自己重画的示意图替代。

## Output contract

- `notes.md`：内容底稿，Markdown，结构标记完整，用户可独立阅读和修改。
- `main.typ` + `prelude.typ`：可独立编译，顶部三行固定为 import + `scholia.with` + `use-palette`。
- `out.pdf`：编译产物；需要确认效果时附 `page-N.png`。
- 编译输出里 `warning: unknown font family` 可忽略，`error:` 一条都不能留。

## Failure handling

- `#include "prelude.typ"` 后报 `unknown variable: accent`：prelude 必须用 `#import "prelude.typ": *`，include 拿不到作用域。
- 注入的配色没生效：`#show: use-palette` 必须写在 `#show: scholia.with(...)` 之后。
- `accent(裸中文, tone: …)` 报 `unknown variable`：圆括号是 code 模式，裸中文被当变量名，用方括号 `#accent[中文]`。
- **渲染位置不对但不报错**：knot 的内容块是位置参数，`[a]`=标题、`[a][b]`=标题+正文、`[a][b][c]`=标题+标签+正文。
  写了三个块却以为「标题+正文」时第二个块会被渲染成小字标签——**退出码 0，grep `error:` 抓不到**，只能看 PNG 发现。
- 公式报 `unknown variable` 或渲染出字面量（`$a_(ij)$`、`$rank(A)$`、`$\overline{A}$` 等）：正确写法见
  `references/troubleshooting.md` §8；这类错应在 Markdown 阶段就改掉。
- **几条公式并排 `a \qquad b`**：工具把 `\qquad` 映射成 2em 的 `wide`、`\quad` 映射成 1em 的 `quad`，直接排就对了；
  **不要**写脚本拆成多个公式块。一行真放不下时再拆独立 `$$` 块。
- **行内 `$1/r$`**：工具在行内把 `/` 排成平排斜杠，只有独占一行的 `$$` 才排上下分式；看到 `1/r` 不必手改成 `r^{-1}`。
- **讲义抬头多行引用块**（`> **来源**：…`）两条链路都排成左侧细线灰色小字块、字段自动换行；不要为「排版」改成普通段落。
- 方框预算按**最小**小节统计：`## 二、分章详解` 下挂 7 个 `### 2.x` 时每个 `2.x` 各自 ≤2 即可。
- 标题编号重复、`sidenote` 的 `symbol` 写法、首次编译卡包：见 `references/troubleshooting.md` §5–§7。
- 用户要的是中文论文/长文排版而非填空笔记：本 skill 不适用，转 `typst-author-chinese`。

## Examples

**输入**：「用 scholia 做一份线性代数期中复习提纲，要能填空自测。」

**输出**：
1. `notes.md`：5 个章节（行列式／线性方程组／向量空间／特征值／自测清单），
   每条按 `[直觉] [定义] [定理] [证明] [例] [练习] [边注]` 标记，公式写成 LaTeX。
2. `prelude.typ` 复制到项目目录；`main.typ` 顶部三行 setup，正文以近黑段落为主，
   强调用 `#mark-key[特征值]` 这类行内淡色，**全篇只有 6 个框**（每个都是后面会被引用的那几条）。
3. `out.pdf` 编译通过（exit 0）；逐页 PNG 看一遍——框的内容块错位不报错，只有看图才发现。

## Windows (win32) platform notes

- 用 Read/Write 工具写 `.md`/`.typ`，不要用 `Set-Content`（PowerShell 5.1 默认 ANSI 会破坏 UTF-8 中文）。
- 编译 / 逐页 PNG / 指定页 / `typst fonts` 命令、字体告警处理、对外分发前 `pdffonts out.pdf` 核对商业字体回退：
  见 [`references/troubleshooting.md`](references/troubleshooting.md)；实际字体表见
  [`references/typography-spec.md`](references/typography-spec.md) §1 与 §8。

## 许可与致谢

- 本 skill（工作流说明、配色方案、`prelude.typ` 扩展、`mapping` / `style` / `troubleshooting` 文档）以 **MIT** 发布，
  见 [`LICENSE`](LICENSE)；逐条归属见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
- 排版引擎 [`@preview/scholia`](https://typst.app/universe/package/scholia)（MIT © Eric Yang）及其依赖已
  **vendor 进 `zju_lecture/typst-packages/`**（保留各自许可文件）；本项目对 `src/fonts.typ` / `src/lib.typ` 的补丁记录在 `VENDORED.md`。