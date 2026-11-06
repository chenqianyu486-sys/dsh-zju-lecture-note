// ─────────────────────────────────────────────────────────────
// scholia 淡彩极简 prelude（实测于 Typst 0.15.1 / Windows）
//
// 单一来源：zju_lecture/prelude.typ
// 生成副本：skills/scholia-notes/references/prelude.typ
// 同步方式：python tools/sync_skill_assets.py
// （tests/test_study_notes.py 会校验两者逐字节一致；改配色只改权威副本再同步）
//
// 用法：把本文件放在 main.typ 同目录，然后
//
//   #import "prelude.typ": *
//   #show: scholia.with(theme: "light", prose: "notes")
//   #show: use-palette
//
// 注意两点（都是实测踩过的坑）：
//  1. 必须用 #import，不能用 #include —— include 后 #let 拿不到作用域，会报 unknown variable。
//  2. #show: use-palette 必须排在 #show: scholia.with(...) 之后，否则会被包装器重置回 light。
// ─────────────────────────────────────────────────────────────

// prelude 自己 import scholia，才能拿到 active 这个 state
#import "@preview/scholia:0.1.0": *

// ── 1. 淡彩配色：按「内容类型」分配色相 ──
// 逻辑：蓝=结论推理 / 青绿=定义术语 / 琥珀=例子练习 / 紫=易错警示 / 灰=次要 / 黑=正文
// 四色对纸白对比度 6.27 / 5.82 / 5.25 / 6.36，极差 1.11 => 视觉重量等同，像一套配色。
// `warn` 是本项目扩展的角色（scholia 原生只用 thm/def/eg/tag/keyword，多余键无害）。
#let soft-palette = (
  dark: false,
  bg: rgb("#FDFDFB"),      // 纸白，比纯白略暖，长时间阅读不刺眼
  ink: rgb("#1A1A1C"),     // 正文接近黑，是全篇阅读负担最低的部分
  muted: rgb("#6F7683"),   // 次要文字：页码、边注、aside
  hairline: rgb("#DBDFE6"),// 分隔线
  fillin: rgb("#8E97A3"),  // 填空线：灰色 —— 告诉读者「这是留给你的」
  thm: rgb("#33609B"),     // 蓝  · 结论族：theorem/lemma/proposition/corollary/proof/qed
  def: rgb("#20705F"),     // 青绿· 定义族：definition/axiom/assumption/notation/remark
  eg: rgb("#8F6218"),      // 琥珀· 例子族：example/yourturn/TODO/workspace
  warn: rgb("#6350A8"),    // 紫  · 易错点（项目扩展，配合 warn 使用）
  rule: rgb("#93A6C4"),    // 标题下的横线（蓝系，呼应结论族）
  tag: rgb("#20705F"),     // 来源标签：归入定义族（术语/出处同属「定」）
  keyword: rgb("#20705F"), // 关键词：归入定义族
)

#let use-palette(body) = {
  active.update(soft-palette)
  body
}

// ── 2. 轻量强调：视觉负担远小于色块，优先用它 ──
// tone: "thm"(蓝·结论) | "def"(青绿·术语) | "eg"(琥珀·例题)
//     | "warn"(紫·易错) | "keyword" | "tag" | "muted"
// 关键：带命名参数必须用圆括号 #accent([内容], strong: true)
#let accent(body, tone: "thm", strong: false) = context {
  text(
    fill: active.get().at(tone),
    weight: if strong { "bold" } else { "regular" },
  )[#body]
}

// 术语：粗体 + 青绿，全篇最常用的强调（术语属「定义族」）
#let mark-key(body) = accent(body, tone: "keyword", strong: true)

// 易错点：粗体 + 紫。刻意不做成方框，避免多一个色块。
#let warn(body) = accent(body, tone: "warn", strong: true)

// 重点：蓝色文字段落（不是方框）。用于 `> [!IMPORTANT]`：块级容器只提供
// 段距与首行缩进，没有底色 / 竖线，读起来仍是正文。
#let keypoint(body) = context block(
  width: 100%,
  above: 6pt,
  below: 6pt,
  {
    set text(fill: active.get().thm)
    h(2em)
    body
  },
)

// ── 3. 细分隔线：比方框轻得多的段落切分 ──
#let divider = context block(width: 100%, above: 0.6em, below: 0.6em)[
  #line(length: 100%, stroke: 0.4pt + active.get().hairline)
]

// ── 4. 无框的行内旁注（比 #note 轻） ──
#let aside(body) = context text(
  fill: active.get().muted,
  size: 0.9em,
)[#body]

// ── 4b. 引用 / 来源块：左侧细线 + 灰色小字 ──
// Markdown 的 `>` 引用在 Typst **没有**对应语法（会原样印出 `>`），
// 讲义抬头（来源 / 上课时间 / ASR 说明）统一走这个助手。
#let quoted(body) = context block(
  width: 100%,
  inset: (left: 12pt, y: 2pt),
  stroke: (left: 2pt + active.get().hairline),
)[#text(size: 0.95em, fill: active.get().muted)[#body]]

// ── 5. 填空线：灰色，不是黑色 ──
// 上游的 fillin 用 ink（近黑）画底线，读起来像印刷内容。
// 练习块里那些线是**留给读者写字**的地方 —— 改成灰色，读者一眼就知道该往哪写。
#let fillin(width: 2.2cm) = context box(
  width: width,
  height: 0.9em,
  stroke: (bottom: 0.6pt + active.get().fillin),
)

// ── 5b. 自测题：题干琥珀框，答案排在框外 ──
// Markdown 里的 `<details><summary>答案</summary>…</details>` 由渲染器映射成
// 这两个装置：题干进 #selftest（与「例」同款的琥珀方框），答案进 #answer
// （左侧一条淡灰细线 + 「答案」小标签）。题目与答案因此有一道清楚的边界，
// 不会像以前那样连成一篇。
#let selftest(number, body) = context {
  let p = active.get()
  block(
    width: 100%,
    breakable: true,
    fill: tint(p, p.eg),
    stroke: (left: 2pt + p.eg),
    inset: (left: 11pt, right: 10pt, top: 7pt, bottom: 7pt),
    above: 14pt,
    below: 2pt,
    {
      set align(left)
      text(font: default-fonts.sans, weight: "bold", size: 0.92em, fill: p.eg)[自测题 #number]
      h(0.4em)
      body
    },
  )
}

#let answer(label, body) = context {
  let p = active.get()
  block(
    width: 100%,
    breakable: true,
    inset: (left: 12pt, right: 10pt),
    stroke: (left: 1.2pt + p.hairline),
    above: 4pt,
    below: 16pt,
    {
      set align(left)
      text(font: default-fonts.sans, weight: "bold", size: 0.9em, fill: p.muted)[#label]
      v(0.25em)
      body
    },
  )
}

// ── 6. 封面包装 ──
// 调用处只传命名参数（`#scholia-cover(title: "...")`），值由渲染器按
// Typst 字符串字面量转义；位置参数一旦被注入的引号截断，后面就能接
// `#read(...)` 之类的可执行代码。
#let scholia-cover(title: "", subtitle: none, author: none, date: none, kicker: none) = {
  cover(title, subtitle: subtitle, author: author, date: date, kicker: kicker)
}

// ── 7. 类型速查（写正文时照着选色相） ──
//   结论/定理/证明/回指  → thm  蓝
//   定义/公理/术语/标签  → def  青绿
//   例子/练习/填空缺口   → eg   琥珀
//   易错/常见陷阱        → warn 紫   ← 项目扩展
//   旁注/页码/分隔线     → muted 灰
//   正文                 → ink   近黑
