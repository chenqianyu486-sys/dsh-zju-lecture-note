# 排版规范（scholia-notes）

**规范性文件。** 本文件定义两条 PDF 链路（阅读版讲义、填空笔记）**统一后**的
字体、字号、行距、版心、装置参数与配色。任何实现都必须符合这里；实现位置见
每节的「实现位置」列，**不要**在别处再写一份数值。

> **口径**：填空式学习笔记是**基于 Typst scholia 模板排版**的产物；配色与段落规范
> 由本项目定义（本文件），不是上游默认值。阅读版讲义是自包含模板，视觉上参考
> scholia 的浅色 notes 主题、未拷贝其源码。

> 配套文件：
> - [`format-spec.md`](format-spec.md) —— 语义对应、预算、禁止事项、数学写法
> - [`style.md`](style.md) —— 配色与视觉预算的**理由**（数值以本文件为准）
> - [`api.md`](api.md) —— 上游 `@preview/scholia` 的 API 事实；本项目对 vendored
>   副本的修改见 [`../../../zju_lecture/typst-packages/VENDORED.md`](../../../zju_lecture/typst-packages/VENDORED.md)

## 0. 总原则

1. **正文是主角，框框是例外。** 框唯一的正当理由是「后面会被引用/回指」。
2. **两条链路同一套字、同一套版心、同一套装置参数。** 读者不应该因为「这是阅读版」
   还是「这是填空版」而看到不同的字号或页边距。
3. **能再分发的字体才能进可分发的 PDF。** 商业字体只以注释形式留在模板里。
4. **数值先量再改。** 版心、边注位置、字号这类视觉量，先用 PDF 坐标量出实际值，
   再改参数；不要凭印象写数字。

<!-- typography-params
page.body.left = 2.4cm
page.body.right = 3.9cm
page.body.top = 2.0cm
page.body.bottom = 2.3cm
page.cover.margin = 2.5cm
page.note.width = 2.6cm
page.note.gap = 0.7cm
body.size = 11pt
body.leading = 0.72em
body.spacing = 0.95em
body.indent = 2em
body.formula = 1.6em
body.inline-math.top = 0.12em
body.inline-math.bottom = 0.10em
body.inline-math.tall = 0.30em
list.spacing = 0.7em
list.indent = 1.5em
cover.kicker = 10pt
cover.title = 30pt
cover.subtitle = 13pt
cover.author = 11pt
cover.date = 9pt
heading.h1 = 15pt
heading.h2 = 12.5pt
heading.h3 = 11.5pt
heading.h1.above = 20pt
heading.h1.below = 12pt
heading.h2.above = 12pt
heading.h2.below = 0.85em
heading.h3.above = 9pt
heading.h3.below = 0.65em
note.size = 0.92em
note.inset = 11pt,9pt,6pt,6pt
note.line = 1.6pt
note.space = 8pt
knot.inset = 12pt,11pt,8pt,8pt
knot.line = 2.2pt
knot.space = 10pt
yourturn.inset = 11pt,10pt,7pt,8pt
yourturn.line = 2pt
yourturn.space = 9pt
sidenote.size = 0.82em
sidenote.leading = 0.5em
sidenote.spacing = 0.4em
footer.size = 0.8em
fillin.width = 2.2cm
fillin.height = 0.9em
fillin.stroke = 0.6pt
divider.space = 0.6em
divider.stroke = 0.4pt
-->

> 上面 `typography-params` 注释块是给测试解析的机器可读副本；正文里的表格与它
> 必须逐项一致。改数值时先改这里，再改实现，最后跑
> `python -m unittest tests.test_typography_unified`。

## 1. 字体

### 1.1 角色与回退链

| 角色 | 用途 | 回退链（首选 → 兜底） | 许可 | 实现位置 |
| :--- | :--- | :--- | :--- | :--- |
| `body` | 正文 | `STIX Two Text` → `Libertinus Serif` → `Notes Kai SC` → `Notes Serif SC` → `Noto Serif SC` → `Source Han Serif SC` | OFL / OFL / OFL / OFL / OFL / OFL | 阅读版 `handout_prelude.typ`；填空版 vendored `src/fonts.typ` + `src/lib.typ` |
| `heading` | 各级标题、封面标题、证明标签、方框标题（`(标题)` 括号里那段斜体） | 同 `body` | 同上 | 同上 |
| `sans` | **方框标签**（Definition / Theorem / Example / Your turn）、直觉块、边注、页码、封面副标题/作者/日期 | `Noto Sans` → `Liberation Sans` → `DejaVu Sans` → `Notes Kai SC` → `Notes Serif SC` → `Noto Serif SC` → `Source Han Serif SC` | OFL / OFL / 自由 / OFL / OFL / OFL / OFL | 同上 |
| `math` | 行内 / 块级公式 | `STIX Two Math` → `New Computer Modern Math` | OFL / OFL（Typst 内嵌） | 同上 |
| `mono` | 行内 / 块级代码 | `DejaVu Sans Mono` → `Notes Kai SC` → `Notes Serif SC` | 自由 / OFL / OFL | 同上 |
| `cjk` | 中文回退（追加在 `body` / `sans` 之后） | `Notes Kai SC` → `Notes Serif SC` → `Noto Serif SC` → `Source Han Serif SC` | OFL | 同上 |

- `sans` **必须是另一族字形**：正文是衬线 + 楷体，方框标签若也用衬线会糊进正文，
  没有「这是一个框」的层次感（上游用 Optima，同样是无衬线）。
- `sans` 里**不排 `Noto Sans SC`**：本机那份是可变字体，Typst 只取到 Thin，
  中文会发灰发轻；中文继续用随包 `Notes Kai SC`。
- `STIX Two` 与 `Notes Kai SC` / `Notes Serif SC` 由本插件随包或由用户安装；
  `Libertinus Serif`、`New Computer Modern`、`DejaVu Sans Mono` 由 **Typst 运行时内嵌**，
  任何机器都有。
- **禁止**把 `Optima` / `Avenir Next` / `Menlo` / `Songti SC` / `SimSun` /
  `Microsoft YaHei` / `Consolas` 放进生效的字体列表。它们是商业专有字体，
  命中后会被子集嵌入 PDF，产物就不能对外分发。模板里可以留注释版的「本机观感」，
  但那种 PDF 不要分享。
- 生僻字不在随包子集里时，Typst 会继续回退；如果回退到系统商业字体，
  `pdffonts out.pdf` 会显示出来 —— 这份 PDF 不宜对外分发（见 §8）。

### 1.2 随包字体

| 文件 | 上游 | 许可 | 说明 |
| :--- | :--- | :--- | :--- |
| `zju_lecture/fonts/NotesKaiSC-Subset.ttf` | LXGW WenKai（霞鹜文楷）v1.530 | SIL OFL 1.1（`OFL-Kai.txt`） | GB2312 子集，**改名**（上游有 Reserved Font Name） |
| `zju_lecture/fonts/NotesSerifSC-Subset.ttf` | Noto Serif SC | SIL OFL 1.1（`OFL.txt`） | GB2312 子集，**改名** |

分发这两个字体（含随 PDF 嵌入）时必须同时提供对应的 `OFL*.txt` 与
`zju_lecture/fonts/FONT-NOTICE.md`；不得单独售卖字体；不得改回上游名称。

## 2. 字号

| 装置 | 字号 | 其它 | 实现位置 |
| :--- | :--- | :--- | :--- |
| 正文 | 11pt | `ink` 色 | 两条链路的 `set text` |
| 一级标题（章） | 15pt | 粗体；编号 `muted`、标题 `thm`；下方 1.1pt `rule`；上 20pt / 下 12pt | 阅读版 `handout_prelude.typ`；填空版 vendored `lib.typ` |
| 二级标题（节） | 12.5pt | 粗体，`def` 色；上 12pt / 下 0.85em | 同上 |
| 三级标题 | 11.5pt | 粗体，`thm` 色；上 9pt / 下 0.65em | 同上 |
| 封面 kicker | 10pt | 全大写，字距 3pt，`muted` | 同上 |
| 封面标题 | 30pt | 粗体，字距 1.5pt，`thm` | 同上 |
| 封面副标题 | 13pt | `muted` | 同上 |
| 封面作者 | 11pt | 字距 0.5pt，`ink` | 同上 |
| 封面日期 | 9pt | 字距 0.5pt，`muted` | 同上 |
| 直觉块 `note` | 0.92em ≈ 10.1pt | `sans`，`ink` | 同上 |
| 边注 `sidenote` / `recall` | 0.82em ≈ 9pt | `sans`，`muted` | 同上 |
| 来源标签 `label-it` | 8pt | 粗体 `sans`，`tag` 色 | 同上 |
| 页码 | 0.8em ≈ 8.8pt | `sans`，`muted`，右对齐 | 同上 |
| 填空线 | 高 0.9em | 底线 0.6pt，`fillin` 灰 | `prelude.typ` / 阅读版模板 |
| 公式 | 随 `math` | 独立于正文字号 | 两条链路 |

## 3. 行距、段距与缩进

| 项 | 值 | 说明 |
| :--- | :--- | :--- |
| 行距 `leading` | **0.72em** | 行与行之间 |
| 段距 `spacing` | **0.95em** | 段与段之间，比行距略大 |
| 列表序号间距 `list.spacing` | **0.7em** | `-` 与 `1.` 的相邻条目之间；默认值/0.3em 实测太挤 |
| 列表缩进 `list.indent` | **1.5em** | 两条链路一致 |
| 正文段首缩进 | **2em**（两格） | 只用于正文段落；用 `#h(2em)` 顶首行 |
| 直觉块首行 | **不缩进** | 块自身的左内边距已经与正文分开（参考图口径） |
| 块级公式上下 | **1.6em** | 显式给出，不跟随 `par.spacing` |
| 行内公式上下（基础） | 上 **0.12em** / 下 **0.10em** | 每个行内公式都补；见 §3.2 |
| 行内公式下留白（高公式） | **0.30em** | 只给分式/根式/矩阵/大算子的上下限；见 §3.2 |
| `justify` | **false** | 两端对齐会把中文字距拉松 |
| `first-line-indent` | **0pt** | 配合 `#h(2em)`，避免双重缩进 |

### 3.1 两条实现铁律

- **段首缩进不用 `par.first-line-indent`，改用 `#h(2em)`。**
  Typst 只在「前一个兄弟元素是段落」时才应用首行缩进；标题后、块后、图后、公式后的
  段落一律不缩进。`#h(2em)` 是行内元素，顶开首行、第二行回版心，与位置无关。
- **独占一行的公式必须写成 `$ … $`（两侧留空格）。**
  Typst 只有在 `$` 之后有空白时才把它当**块级公式**（居中 + 独立上下间距）；
  写成 `$x$` 只是行内公式，靠左排，还会吃掉那一行的首行缩进。

### 3.2 行内公式的上下留白（`body.inline-math.*`）

**现象**：纯文字行的行距正常，但**含行内公式的行明显拥挤**——分式的分子/分母、
根式、积分/求和的上下限压到邻行上，甚至与下一行重叠 1–4pt。

**原因**（实测，Typst 0.15.1）：行内数学盒子的高度是**固定值**（11pt 下约
`0.68em`，与内容无关）。`measure($frac(1,2)$)` 与 `measure($x$)` 都返回
`7.51pt`，而 `\frac` 的墨迹实际高约 21pt。溢出部分不会撑开行盒，`par.leading`
照常只按固定高度加，于是墨迹撞进邻行。这是排版引擎的行为，**不是**行距参数写错了。

**做法**（两处，都是显式留白）：

1. **基础留白**：`#show math.equation.where(block: false): it => box(inset: (top: 0.12em, bottom: 0.10em), it)`
   ——每个行内公式都补一点，上下标也受益。放在阅读版模板里（`handout_prelude.typ` 内联生效），
   填空笔记链路由 `render_typst` 写进 `main.typ` 的固定头部（`prelude.typ` 是 `#import`，
   里面的 `#show` 不会带到文档里）。
2. **高公式补下留白**：渲染器 `pad_inline_math()` 识别「结构上必然溢出」的公式
   （`frac` / `sqrt` / `root` / `binom` / `mat` / `cases` / `integral` / `sum` /
   `prod` / `lim` 等，按**转换后的 Typst 形态**判断），再包一层
   `#box(inset: (bottom: 0.30em), $…$)`。

为什么不全用固定留白：按最大高度（约 0.45em）给，会把只有 `$x$` 的行也撑松，
整页节奏就散了。按结构分级后，实测同一份讲义：行间距 < 2pt 的行对从 37 降到 15，
最差的一处从 −3.74pt（重叠）升到 +1.19pt；纯文字行的行距一点没动。

块级公式（`$ … $`）**不加**这层：它的上下间距由 §3 的 `body.formula` 负责。

固定头部（工具自动写，手工排版照抄）：

```typst
#set text(lang: "zh")
#set par(
  justify: false,
  leading: 0.72em,
  first-line-indent: 0pt,
  spacing: 0.95em,
)
#set list(indent: 1.5em, spacing: 0.7em)
#set enum(indent: 1.5em, spacing: 0.7em)
#show math.equation.where(block: true): set block(above: 1.6em, below: 1.6em)
#show math.equation.where(block: false): it => box(inset: (top: 0.12em, bottom: 0.10em), it)
```

## 4. 版心与边注

| 项 | 值 | 说明 |
| :--- | :--- | :--- |
| 纸张 | A4 | 595.28 × 841.89pt |
| 正文版心 | 左 **2.4cm** / 右 **3.9cm** / 上 **2.0cm** / 下 **2.3cm** | 正文列宽 14.7cm |
| 封面版心 | 左右各 **2.5cm**（对称）/ 上 2.0cm / 下 2.3cm | 封面在物理页面上居中 |
| 边注栏宽 | **2.6cm** | 右栏 |
| 边注栏与版心间距 | **0.7cm** | 实测：版心右边界 17.1cm，边注左边界 17.8cm |
| 边注到页边 | 0.6cm | 边注右边界 20.4cm |
| 页码 | 封面/目录不占页码；正文第一页从 1 起 | 页脚右对齐 |

实测校验（同一份内容、A4、150 DPI）：正文左边界 68.03pt、右边界 484.72pt、
边注左边界 504.57pt；两条链路必须一致（误差 ≤ 2pt）。

## 5. 框与块

| 装置 | 内边距（左/右/上/下） | 左竖线 | 上下外距 | 底色 | 实现位置 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 定理/定义/例框 `knot` | 12 / 11 / 8 / 8pt | 2.2pt | 10pt | 强调色 9% 混纸白 | 阅读版 `knot`；填空版 vendored `theorems.typ` |
| 直觉块 `note` | 11 / 9 / 6 / 6pt | 1.6pt | 8pt | `thm` 9% | 阅读版 `note`；填空版 vendored `lib.typ` |
| 练习块 `yourturn` | 11 / 10 / 7 / 8pt | 2pt | 9pt | `eg` 9% | 同上 |
| 证明段 `proof` | — | — | 上 6pt / 下 8pt | — | 阅读版 `proof`；填空版 vendored `theorems.typ` |
| 书写位 `workspace` | — | — | 3 行，行距 9pt | 0.3pt `hairline` | 阅读版 / 填空版 |
| 填空线 `fillin` | — | — | — | 宽 2.2cm、高 0.9em、底线 0.6pt `fillin` | `prelude.typ` / 阅读版模板 |
| 分隔线 `divider` | — | — | 上下 0.6em | 0.4pt `hairline` | 同上 |
| 边注 `sidenote` | — | — | — | 0.82em、行距 0.5em、段距 0.4em、宽 2.6cm | 阅读版 `sidenote`；填空版 vendored `lib.typ` + marginalia |

- 框的**逐节预算**与「方框 : 正文」比值见 [`format-spec.md`](format-spec.md) §2.2–2.3。
- 练习块里不再画短填空线；正文里的 `____` 仍画成灰色填空线。
- 证明段用斜体 `Proof.` + 行末 6pt 实心方块（qed）；qed 的位置随正文换行，
  两条链路行为一致。

## 6. 封面与目录

固定模板（工具自动生成，手工排版照抄）：

```typst
#cover(title, subtitle: none, author: none, date: none, kicker: none)
```

| 顺序 | 元素 | 参数 |
| :--- | :--- | :--- |
| 1 | 顶部弹性空白 | `v(1fr)` |
| 2 | kicker | 10pt、全大写、字距 3pt、`muted`；下方 `v(0.9cm)` |
| 3 | 标题 | 30pt、粗体、字距 1.5pt、`thm`；下方 `v(0.5cm)` |
| 4 | 横线 | 32% 宽、1pt、`rule` |
| 5 | 副标题 | 13pt、`muted`；上方 `v(0.5cm)` |
| 6 | 中部弹性空白 | `v(1fr)` |
| 7 | 作者 | 11pt、字距 0.5pt、`ink` |
| 8 | 日期 | 9pt、字距 0.5pt、`muted`；上方 `v(0.3em)` |
| 9 | 底部空白 | `v(1.6cm)` |

封面与目录都不显示页码；排完后把页码重置为 1，正文第一页从 1 开始。

## 7. 颜色

### 7.1 单一来源

浅色主题「淡彩极简」是本项目自定义的，唯一权威副本是
`zju_lecture/prelude.typ` 的 `#let soft-palette`。另外两处是生成副本，不能手改：

| 生成副本 | 谁同步 |
| :--- | :--- |
| `zju_lecture/handout_prelude.typ` 的 `#let palette` | `python tools/sync_palette.py` |
| `zju_lecture/handout.py` 的 `_PALETTE` | 同上 |

改配色只改 `zju_lecture/prelude.typ`，然后跑同步脚本与测试。

### 7.2 角色与色值

| role | 色值 | 对比度 vs 纸白 | 用途 |
| :--- | :--- | :--- | :--- |
| `bg` | `#FDFDFB` | — | 纸白页面底色 |
| `ink` | `#1A1A1C` | 17.06 | 正文 |
| `thm` | `#33609B` | 6.27 | 蓝 · 结论族 |
| `def` | `#20705F` | 5.82 | 青绿 · 定义族 |
| `eg` | `#8F6218` | 5.25 | 琥珀 · 例子族 |
| `warn` | `#6350A8` | 6.36 | 紫 · 易错警示 |
| `muted` | `#6F7683` | 4.49 | 灰 · 次要 |
| `fillin` | `#8E97A3` | 2.90 | 灰 · 填空线 |
| `rule` | `#93A6C4` | 2.43 | 标题横线 |
| `hairline` | `#DBDFE6` | 1.31 | 分隔线 |

`tag` / `keyword` = `#20705F`。块底色由 `tint()` 按 9% 混向 `bg`（深色 16%）。

### 7.3 强调色等权

四个强调色对纸白的对比度：`thm 6.27` / `def 5.82` / `eg 5.25` / `warn 6.36`，
**极差 1.11**（刻度上的跨度，不是比值）。改色时必须重算并保持 ≤ 1.2；
否则一页看上去就成了「一主两辅」。

## 8. 校验清单

工具自动做的：

- [x] 编译错误一条不留（`error:` 即失败）
- [x] 方框逐节计数与全篇「方框 : 正文」比值（见 `format-spec.md`）
- [x] 规范参数与实现参数一致（`tests/test_typography_unified.py`）
- [x] 两条链路渲染同一份内容，正文左/右边界、边注左边界误差 ≤ 2pt
- [x] `pdffonts` 里不出现商业字体（有 poppler 时）

**必须人做的**：

- [ ] **看逐页 PNG**：框的内容块错位不会报错（`#theorem[标题][正文][多余内容]`
      里的第二块会被当成来源标签渲染成小字，退出码仍是 0）。
- [ ] 对外分发前跑一次 `pdffonts out.pdf`，确认没有 `Optima` / `Avenir Next` /
      `Menlo` / `Songti SC` / `SimSun` / `Microsoft YaHei`。
- [ ] 确认方框确实都是「值得被引用」的那几个。

## 9. 内容归属（写进规范，不是可选项）

- 定理、公式、结论的**事实**不受著作权保护，但**特定表达**受保护：复述用自己
  的句子，并注明出处（教材 / 课件 / 课堂时间戳）。
- 习题、习题答案、教材例题原文**不整段照搬**；需要引用时改写并标注来源。
- 课堂截图 / PPT 画面属于授课教师与学校；不要原样嵌进要公开分发的笔记。
  讲义里的截图索引可以保留，但对外发布前先确认授权。
- 本插件与 `@preview/scholia` 的作者**无隶属关系、未获背书**；「scholia」只用于
  指代所依赖的包（指示性使用）。不使用上游的 logo、预览图、作者头像。

## 10. 实现位置

| 内容 | 阅读版讲义 | 填空笔记 |
| :--- | :--- | :--- |
| 页面 / 封面 / 标题 / 边注 / 装置 | `zju_lecture/handout_prelude.typ` | vendored `zju_lecture/typst-packages/preview/scholia/0.1.0/src/lib.typ` |
| 字体表 | `handout_prelude.typ` 的 `#let fonts` | vendored `src/fonts.typ` 的 `#let default-fonts` |
| 配色 | `handout_prelude.typ` 的 `#let palette`（生成副本） | `zju_lecture/prelude.typ` 的 `soft-palette` |
| 正文参数 | `handout_prelude.typ` 的 `#set par` | `zju_lecture/study_notes.py` 的 `render_typst` setup |
| 字体文件 | `zju_lecture/fonts/` | 同左 |
| 修改记录 | 本文件 / `CHANGELOG.md` | `zju_lecture/typst-packages/VENDORED.md` |

> 本文件是排版数值的唯一真相源。`format-spec.md`、`style.md`、`docs/technical.md`
> 只保留语义、理由与机制，数值一律指向这里。
