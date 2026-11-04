// ─────────────────────────────────────────────────────────────
// scholia 淡彩极简起步模板（实测于 Typst 0.15.1）
// 先写 notes.md 定内容，再回来填这个文件。
// 编译：typst compile main.typ out.pdf
//
// 配色按内容类型分（蓝=结论 / 青绿=定义 / 琥珀=例子 / 紫=易错 / 灰=次要 / 黑=正文），
// 对应关系全篇固定，见 references/style.md 第 2 节。
// ─────────────────────────────────────────────────────────────

// setup：三行固定，顺序不能换
#import "prelude.typ": *
#show: scholia.with(theme: "light", prose: "notes")
#show: use-palette

// 中文正文：段首空两格、段间距略大于行距、块级公式单独给间距
#set text(lang: "zh")
#set par(
  justify: false,
  leading: 0.72em,
  first-line-indent: 0pt,
  spacing: 0.95em,
)
#show math.equation.where(block: true): set block(above: 1.6em, below: 1.6em)
// 行内公式的上下留白：Typst 的行内数学盒子高度固定（≈0.68em），分式的分子/分母、
// 根式、大算子的上下限会溢出盒子压到邻行。数值见 typography-spec.md §3.2。
#show math.equation.where(block: false): it => box(inset: (top: 0.12em, bottom: 0.10em), it)

#cover(
  "章节总标题",
  subtitle: "一句话副标题",
  author: "作者",
  date: "2026",
  kicker: "MATH 201",   // 标题上方的小字行
)

= 一、章节标题

普通段落：接近黑的正文色，是整份笔记的主体。先把话讲清楚，样式能省则省。

这一句里#mark-key[特征值] 是青绿术语；#accent([这条结论])是蓝色结论。
#warn[易错点：这里最容易漏边界条件。] 是紫色警示，行内不占版面。

#divider

#note[
  整节只用一个带底色的块讲直觉。这层是*读*的，下面几层是*填*的。
]

== 小节标题（编号自动生成，别手写）

#definition[术语][一句话说清对象，关键从句留空：#fillin(width: 2.5cm)。] <def:term>

#theorem[可选标题][可选来源标签][正式结论全文，后面可以回指 @def:term。] <thm:main>

#proof[
  证明骨架：(i) 第一步；(ii) 第二步。关键那一步留空：
  #TODO[缺哪一步 / 为什么这一步成立]。
]

#example[一个可模仿的例子][完整演示一次计算过程。]

#yourturn[
  把上面的例子改成自己的题目重做一遍。
  #workspace(n: 3)
]

#recall[停在右边栏的主动回忆问题，不占正文版面。]

#aside[灰色小字：可以跳读的弱化补充。]

= 二、下一章

正文段落。knot 编号随一级标题重新从 1 开始，但 `@标签` 引用照常工作。

#remark[不需要框的旁注（实测会居中显示）。]