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

// ── 3. 细分隔线：比方框轻得多的段落切分 ──
#let divider = context block(width: 100%, above: 0.6em, below: 0.6em)[
  #line(length: 100%, stroke: 0.4pt + active.get().hairline)
]

// ── 4. 无框的行内旁注（比 #note 轻） ──
#let aside(body) = context text(
  fill: active.get().muted,
  size: 0.9em,
)[#body]

// ── 5. 填空线：灰色，不是黑色 ──
// 上游的 fillin 用 ink（近黑）画底线，读起来像印刷内容。
// 练习块里那些线是**留给读者写字**的地方 —— 改成灰色，读者一眼就知道该往哪写。
#let fillin(width: 2.2cm) = context box(
  width: width,
  height: 0.9em,
  stroke: (bottom: 0.6pt + active.get().fillin),
)

// ── 6. 类型速查（写正文时照着选色相） ──
//   结论/定理/证明/回指  → thm  蓝
//   定义/公理/术语/标签  → def  青绿
//   例子/练习/填空缺口   → eg   琥珀
//   易错/常见陷阱        → warn 紫   ← 项目扩展
//   旁注/页码/分隔线     → muted 灰
//   正文                 → ink   近黑
