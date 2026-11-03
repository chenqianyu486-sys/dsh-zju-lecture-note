// ─────────────────────────────────────────────────────────────
// 讲义阅读版 PDF 的自包含模板（不依赖 Typst Universe 包）。
//
// 单一来源：zju_lecture/handout_prelude.typ
// 由 zju_lecture/handout.py 读入并内联进 main.typ。
//
// 视觉语言与 scholia 填空笔记同一套（见 format-spec.md）：
//   蓝 = 结论（定理 / 边注的 ?）· 青绿 = 定义 · 琥珀 = 例子 / 练习
//   灰 = 次要（页码 / 边注）· 近黑 = 正文
// 正文是主角：淡彩块只为「需要被编号、被回指」的内容而存在。
//
// 为什么不用 @preview/scholia：讲义 PDF 是默认链路，第一次编译就去
// Typst 包注册表拉依赖，会把「本地排版」变成一次网络请求；这里用
// 标准 Typst 排版，离线也能编译，也不引入额外的第三方包与字体表。
// ─────────────────────────────────────────────────────────────

// ── 1. 配色 ──
// 单一来源是 prelude.typ 的 `#let soft-palette`（见 format-spec.md §5）；
// 这一块由 `python tools/sync_palette.py` 生成，不要手改：
// 改配色只改 prelude.typ，再跑同步脚本（--check 会在测试里守住三处一致）。
// 深色主题由上游 scholia 自带，这本模板只做浅色阅读版。
#let palette = (
  bg: rgb("#FDFDFB"),       // 纸白：页面底色
  ink: rgb("#1A1A1C"),      // 正文
  muted: rgb("#6F7683"),    // 页码 / 边注 / aside
  hairline: rgb("#DBDFE6"), // 分隔线 / 书写位横线
  thm: rgb("#33609B"),      // 蓝 · 结论族
  def: rgb("#20705F"),      // 青绿 · 定义族
  eg: rgb("#8F6218"),       // 琥珀 · 例子族
  warn: rgb("#6350A8"),     // 紫 · 易错（项目扩展）
  rule: rgb("#93A6C4"),     // 标题下横线
  fillin: rgb("#8E97A3"),   // 填空线
)

// 淡彩底：把强调色朝纸白混 9%。
#let tint(base, strength: 9%) = color.mix((base, strength), (palette.bg, 100% - strength))

// ── 2. 字体：默认可再分发 ──
// 上游 scholia 的 heading / sans / mono 首选 Optima / Avenir Next / Menlo 是
// 商业专有字体；Typst 会把命中的字体子集内嵌进 PDF，那份 PDF 就不适合再分发。
// 所以这里默认用 SIL OFL 的 STIX Two，再退到 Typst 运行时内嵌的 Libertinus /
// New Computer Modern / DejaVu —— 任何机器都出字，且产物可以对外分享。
//
// 中文第一顺位是插件自带的 **Notes Kai SC**（LXGW WenKai 的 GB2312 子集，
// OFL，见 zju_lecture/fonts/FONT-NOTICE.md）：参考图的楷体观感在任何机器上
// 都能复现；第二顺位 Notes Serif SC（Noto Serif SC 子集）提供宋体兜底。
// 生僻字不在子集里时，Typst 会继续往后回退到 Noto Serif SC / Source Han
// Serif SC（皆 OFL）；再往后没有系统商业字体，宁可缺字也不把 SimSun /
// Microsoft YaHei 的子集嵌进可分发的 PDF。
#let fonts = (
  body: (
    "STIX Two Text", "Libertinus Serif",
    "Notes Kai SC", "Notes Serif SC",
    "Noto Serif SC", "Source Han Serif SC",
  ),
  heading: (
    "STIX Two Text", "Libertinus Serif",
    "Notes Kai SC", "Notes Serif SC",
    "Noto Serif SC", "Source Han Serif SC",
  ),
  sans: (
    "STIX Two Text", "Libertinus Serif",
    "Notes Kai SC", "Notes Serif SC",
    "Noto Sans SC", "Source Han Sans SC",
  ),
  mono: ("DejaVu Sans Mono", "Notes Kai SC", "Notes Serif SC"),
)
// #let fonts = (
//   body: ("STIX Two Text", "Libertinus Serif", "Noto Serif SC", "Songti SC", "SimSun"),
//   heading: ("Optima", "Libertinus Serif", "Noto Serif SC", "Songti SC", "SimSun"),
//   sans: ("Avenir Next", "Libertinus Serif", "Noto Sans SC", "Microsoft YaHei"),
//   mono: ("Menlo", "DejaVu Sans Mono"),
// )

// ── 3. 版面：右侧留出 3.9cm 的边注栏（左 2.4 / 右 3.9 / 上 2.0 / 下 2.3）──
#set page(
  paper: "a4",
  margin: (left: 2.4cm, right: 3.9cm, top: 2.0cm, bottom: 2.3cm),
  // 纸白而不是纯白：与 palette.bg 一致，淡彩色块也朝这个底色混。
  fill: palette.bg,
  footer: context align(right, text(font: fonts.sans, size: 0.8em, fill: palette.muted)[
    #counter(page).display()
  ]),
)

#set text(font: fonts.body, size: 11pt, lang: "zh", fill: palette.ink)
#show math.equation: set text(font: ("STIX Two Math", "New Computer Modern Math"))

// 中文正文：段首缩进由渲染器写 #h(2em)（与位置无关），这里只负责
// 行距、段距、列表与标题。段间距略大于行间距。
#set par(
  justify: false,
  leading: 0.72em,
  spacing: 0.95em,
  first-line-indent: 0pt,
)
// 块级公式的上下间距**显式**给出，不跟随 par.spacing（否则一压段距就重叠）。
#show math.equation.where(block: true): set block(above: 1.6em, below: 1.6em)

#set list(indent: 1.5em, spacing: 0.3em)
#set enum(indent: 1.5em, spacing: 0.3em)
#set heading(numbering: "1.1")

// ── 4. 标题：编号灰蓝 + 标题蓝，一级标题下一条细横线（参考图的样式）──
#show heading: set text(font: fonts.heading)
#show heading.where(level: 1): it => block(width: 100%, above: 20pt, below: 8pt)[
  #text(size: 15pt, weight: "bold", fill: palette.muted)[#counter(heading).display()]
  #h(0.7em)
  #text(size: 15pt, weight: "bold", fill: palette.thm)[#it.body]
  #v(1pt)
  #line(length: 100%, stroke: 1.1pt + palette.rule)
]
#show heading.where(level: 2): it => block(above: 11pt, below: 0.5em)[
  #text(size: 12.5pt, weight: "bold", fill: palette.def)[#counter(heading).display() #it.body]
]
#show heading.where(level: 3): it => block(above: 8pt, below: 0.4em)[
  #text(size: 11.5pt, weight: "bold", fill: palette.thm)[#it.body]
]

// ── 5. 装置：直觉 / 定义 / 定理 / 例 / 证明 / 练习 / 边注 ──
// 框只给「需要编号、会被回指」的内容；其余用 accent / warn / aside。

#let _knot-color(tone) = if tone == "def" {
  palette.def
} else if tone == "eg" {
  palette.eg
} else {
  palette.thm
}

#let knot(label, number, body, title: none, tone: "thm") = block(
  width: 100%,
  breakable: true,
  fill: tint(_knot-color(tone)),
  stroke: (left: 2.2pt + _knot-color(tone)),
  inset: (left: 12pt, right: 11pt, top: 8pt, bottom: 8pt),
  above: 10pt,
  below: 10pt,
  {
    set align(left)
    text(font: fonts.heading, weight: "bold", fill: _knot-color(tone))[#label #number]
    if title != none {
      text(font: fonts.heading, style: "italic", fill: palette.ink)[ (#title)]
    }
    text(font: fonts.heading, weight: "bold", fill: _knot-color(tone))[.]
    h(0.4em)
    body
  },
)

#let theorem(number, body, title: none) = knot("Theorem", number, body, title: title)
#let lemma(number, body, title: none) = knot("Lemma", number, body, title: title)
#let proposition(number, body, title: none) = knot("Proposition", number, body, title: title)
#let corollary(number, body, title: none) = knot("Corollary", number, body, title: title)
#let definition(number, body, title: none) = knot("Definition", number, body, title: title, tone: "def")
#let axiom(number, body, title: none) = knot("Axiom", number, body, title: title, tone: "def")
#let assumption(number, body, title: none) = knot("Assumption", number, body, title: title, tone: "def")
#let notation(number, body, title: none) = knot("Notation", number, body, title: title, tone: "def")
#let example(number, body, title: none) = knot("Example", number, body, title: title, tone: "eg")

// 直觉：淡蓝底 + 左侧细竖线，语气是「人话版」。
// 块内正文**不缩进**（与填空笔记一致）：块本身的左内边距已经把内容与正文分开。
#let note(body) = block(
  width: 100%,
  breakable: true,
  fill: tint(palette.thm),
  stroke: (left: 1.6pt + palette.thm),
  inset: (left: 11pt, right: 9pt, top: 6pt, bottom: 6pt),
  above: 8pt,
  below: 8pt,
  {
    set align(left)
    set text(font: fonts.sans, size: 0.92em, fill: palette.ink)
    [#body]
  },
)

// 练习：淡琥珀底 + 左侧竖线 + 三行书写位。
#let workspace(n: 3) = {
  v(1pt)
  for _ in range(n) {
    line(length: 100%, stroke: 0.3pt + palette.hairline)
    v(9pt)
  }
}

#let yourturn(body) = block(
  width: 100%,
  breakable: true,
  fill: tint(palette.eg),
  stroke: (left: 2pt + palette.eg),
  inset: (left: 11pt, right: 10pt, top: 7pt, bottom: 8pt),
  above: 9pt,
  below: 9pt,
  {
    set align(left)
    text(font: fonts.heading, weight: "bold", fill: palette.eg)[Your turn.]
    h(0.3em)
    body
    workspace(n: 3)
  },
)

// 证明：不套框，只给斜体 Proof. 与行末的 qed 方块。
// qed 用 box(rect(...)) 而不是裸 rect：rect 是块级元素，会另起一行；
// 填空笔记链路的 mark() 也是 box，两条链路的方块才会都落在行末。
#let proof(body) = block(above: 6pt, below: 8pt, {
  text(font: fonts.heading, style: "italic", fill: palette.muted)[Proof.]
  h(0.4em)
  body
  h(1fr)
  box(baseline: 1pt, rect(width: 6pt, height: 6pt, fill: palette.thm, radius: 0.5pt, inset: 0pt))
})

// 旁注：不套框，斜体青绿。
#let remark(body) = block(above: 8pt, below: 8pt, {
  text(font: fonts.heading, style: "italic", fill: palette.def)[Remark.]
  h(0.4em)
  body
})

// 边注：Tufte 式右栏。`box(width: 0pt)` 把锚点固定在正文行内，
// 再用 place 把内容推进右侧留白（dx 由页面宽度与锚点位置算出）。
#let sidenote(body, symbol: none) = box(
  width: 0pt,
  context {
    let anchor = here().position()
    let note-width = 2.6cm
    // 版心右边界 = 21cm - 3.9cm = 17.1cm；边注左边界 = 21 - 2.6 - 0.6 = 17.8cm，
    // 因此边注与版心的实际间距是 0.7cm（不是 0.6cm；0.6cm 是边注到页边的距离）。
    let dx = page.width - anchor.x - note-width - 0.6cm
    place(
      top + left,
      dx: dx,
      box(width: note-width, {
        set align(left)
        set text(font: fonts.sans, size: 0.82em, fill: palette.muted)
        set par(leading: 0.5em, spacing: 0.4em)
        if symbol != none {
          text(fill: palette.thm, weight: "bold")[#symbol]
          h(0.25em)
        }
        body
      }),
    )
  },
)
#let recall(body) = sidenote(body, symbol: [?])

// ── 6. 行内强调与辅助 ──
#let accent(body) = text(weight: "bold", fill: palette.thm)[#body]
#let warn(body) = text(weight: "bold", fill: palette.warn)[#body]
#let aside(body) = text(size: 0.9em, fill: palette.muted)[#body]
#let gap(hint) = text(font: fonts.sans, size: 0.92em, fill: palette.eg)[[ fill in: #hint ]]
#let fillin(width: 2.2cm) = box(
  width: width,
  height: 0.9em,
  stroke: (bottom: 0.6pt + palette.fillin),
)
#let divider = block(width: 100%, above: 0.6em, below: 0.6em)[
  #line(length: 100%, stroke: 0.4pt + palette.hairline)
]

// ── 7. 代码 / 表格 / 图 / 链接 ──
#show raw.where(block: true): it => block(
  width: 100%,
  inset: 9pt,
  radius: 3pt,
  fill: rgb("#F6F7F9"),
  stroke: 0.4pt + palette.hairline,
  text(font: fonts.mono, size: 9pt)[#it],
)
#show raw.where(block: false): set text(font: fonts.mono, size: 0.9em)

#set table(inset: (x: 8pt, y: 5pt), stroke: none, align: left)
#show table: set text(size: 10pt)
#show table.cell.where(y: 0): set text(weight: "bold")

#show figure: set block(above: 8pt, below: 8pt)
#show figure.caption: set text(size: 9pt, fill: palette.muted)
#show link: set text(fill: palette.thm)

#show outline.entry: set text(size: 10.5pt)
#show outline.entry.where(level: 1): set block(above: 0.6em)

// ── 8. 封面 / 目录 ──
// 封面：独立页、无页码，排完把页码重置为 1（正文第一页从 1 开始）。
#let cover(title, subtitle: none, author: none, date: none, kicker: none) = {
  // 封面用左右对称的版心，才能在物理页面上真正居中（正文版心右侧留了边注栏）。
  page(footer: none, margin: (left: 2.5cm, right: 2.5cm, top: 2cm, bottom: 2.3cm))[
    #v(1fr)
    #align(center)[
      #if kicker != none {
        text(font: fonts.heading, size: 10pt, tracking: 3pt, fill: palette.muted)[#upper(kicker)]
        v(0.9cm)
      }
      #text(font: fonts.heading, weight: "bold", size: 30pt, tracking: 1.5pt, fill: palette.thm)[#title]
      #v(0.5cm)
      #line(length: 32%, stroke: 1pt + palette.rule)
      #if subtitle != none {
        v(0.5cm)
        text(font: fonts.sans, size: 13pt, fill: palette.muted)[#subtitle]
      }
    ]
    #v(1fr)
    #align(center)[
      #if author != none {
        text(font: fonts.sans, size: 11pt, tracking: 0.5pt, fill: palette.ink)[#author]
      }
      #if date != none {
        v(0.3em)
        text(font: fonts.sans, size: 9pt, tracking: 0.5pt, fill: palette.muted)[#date]
      }
    ]
    #v(1.6cm)
  ]
  counter(page).update(1)
}

// 目录：单独一页、无页码；之后把页码重置为 1，正文从 1 开始。
#let toc(depth: 2) = {
  page(footer: none)[
    #v(0.3cm)
    #text(font: fonts.heading, weight: "bold", size: 18pt, fill: palette.thm)[目录]
    #v(0.8em)
    #line(length: 100%, stroke: 0.8pt + palette.rule)
    #v(0.8em)
    #outline(title: none, depth: depth)
  ]
  counter(page).update(1)
}
