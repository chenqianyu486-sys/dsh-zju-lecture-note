# 排错与平台适配（实测于 Typst 0.15.1 / Windows 11）

## 1. `warning: unknown font family` 一大串 —— 可以忽略

两条链路的默认字体表是 `STIX Two` / `Libertinus` / 随包 `Notes Kai SC` 与
`Notes Serif SC` / `Noto` / `Source Han`。本机没装 STIX Two 时会刷告警；
Typst 回退到 Libertinus 或随包字体，中英文照常出字，PDF 完整。
不要为了消告警去改文档结构，也不需要再装 Optima / Avenir Next。

## 2. 中文要不要加 `fonts:` 覆盖

**不用。** vendored `scholia` 的 `default-fonts` 已由本项目 patch 成可再分发栈，
`note` / `sidenote` / `label-it` 也跟随同一套字体；底稿与模板都不需要再写
`fonts:`。要换字形时才覆盖，实际字体表见
[`typography-spec.md`](typography-spec.md) §1。

## 3. `lang` 被写死为 `"en"`

`lib.typ` 里 `set text(..., lang: "en")`，所以中文按西文断行/断词规则处理，`justify: true` 会拉开字距。
中文文档建议：

```typst
#set text(lang: "zh")   # 放在 #show: scholia.with(...) 之后，覆盖包装器的设置
```

想控制两端对齐的松紧，再调 `set par(justify: false)`。

## 4. `remark` 会居中

实测 `#remark[…]` 渲染出来是**居中**的（frame-it 的 figure caption 默认居中，
`knot-style` 里的 `set align(left)` 只对带框分支生效）。要左对齐就把 remark 放到普通段落里，
或者自己包一层 `#block[#align(left)[#remark[…]]]`。

## 5. `sidenote` 的 `symbol` 必须用圆括号

```typst
#sidenote([正文])                      // ✅ 常规写法
#recall([正文])                        // ✅ 等价于 symbol: [?]
#sidenote([正文], symbol: [!])          // ✅ 自定义符号
#sidenote[symbol: [!]][正文]            // ❌ error: unexpected argument
#sidenote(裸中文)                       // ❌ unknown variable：圆括号是 code 模式
```

## 6. 编译卡住不动

现象：`typst compile` 几分钟无任何输出。原因是首次要访问 Typst 包注册表
（`packages.typst.org`）；网络被代理/鉴权拦住时会一直挂着。

- 本地缓存目录：`%LOCALAPPDATA%\typst\packages\preview\`（已有 `scholia`、`frame-it`、
  `marginalia` 时应能秒级编译）。
- 处理：重试一次；仍卡住就把「需要拉包」这件事和依赖名报给用户，别空等。

## 7. 标题编号重复：`1.1 1.1 小节`

包装器已经 `set heading(numbering: "1.1")`，一级标题渲染成 `1`，二级渲染成 `1.1`。
如果正文里手写了编号（`== 1.1 小节`），就会叠成 `1.1 1.1 小节`。
**只写标题文字，不要手写编号。**

## 8. 数学模式里的多字母标识符与 LaTeX 习惯（实测 Typst 0.15.1）

Typst 数学模式**不是 LaTeX**，写数学复习提纲时以下写法必然踩坑（错误信息已逐条验证）：

| 写法 | 结果 | 正确写法 |
|---|---|---|
| `$a_(ij)$` | ❌ `unknown variable: ij` | `$a_(i j)$` ✅ |
| `$Ax = b$` | ❌ 被当成一个标识符 | `$A x = b$` ✅ |
| `$\operatorname{rank}(A)$` | ❌ | `$"rank"(A)$` ✅ |
| `$Var(X)$` | ❌ `unknown variable: Var` | `$"Var"(X)$` ✅ |
| `$\prod_(i=1) a_i$` | ❌ `unknown variable: prod` | `$product_(i=1) a_i$` ✅ |
| `$diag(A)$` | ❌ `unknown variable: diag` | `$"diag"(A)$` ✅ |
| `$\overline{A}$` | ❌ 反斜杠被当转义 | `$overline(A)$` ✅ |
| `$macron.h(A)$` | ❌ `unknown symbol modifier` | `$overline(A)$` ✅ |
| `$underline(A)$` | ✅ | — |
| `$sigma^2$` | ✅ 渲染成 σ² | **裸写，不要加引号** |
| `$sqrt(2)$` | ✅ 渲染成 √2 | **裸写，不要加引号** |
| `$A times B$`、`$A dot B$` | ✅ | 也可直接用 `×`、`·` |

**先裸写，报错才加引号。** 通用原则：多字母标识符一律加空格或加引号
（Typst 的报错 hint 会提示 `try adding spaces between each letter`）。

⚠️ 别把「一律加引号」当铁律：`$"sigma"$` 会渲染成直立文本 `sigma`，
`$"sqrt"(2)$` 会渲染成 `sqrt(2)` 字面量——**两者都能正常编译，没有任何告警**，
只有看 PNG 才发现。多字母**算子/函数名**（rank、Var、nullity、diag）才需要引号；
单个已知符号（sigma、sqrt、product、sum、in、subset…）一律裸写。

## 9. 改配色时颜色「太淡」

踩过的坑：把 `thm` 从 `#33609B` 压到 `#7C8DB5`，彩度是降了，但强调文字几乎消失，
整页发灰。原因是 `tint()` 会把强调色按 9% 混向纸白——强调色一变淡，
`definition` / `theorem` 的块底色会一起褪掉，方框的区分度随之消失。

**淡 = 降彩度，不是降亮度差**。判定：缩到 25% 还看得出重点才够；
或直接对照 `references/style.md` 里的三档表格。

## 10. 内容块里写颜色报错 `invalid number suffix`

在 `[...]` 内容块里直接写 `rgb("#33609B")` 会报 `invalid number suffix: 33609B`——
内容模式下字符串不解析，`"` 后面的 `#` 被当成进入代码模式，于是变成数字 `#33609B`。

```typst
#show: use-p[(thm: rgb("#33609B"))]     // ❌ 报错
#show: use-p[#(thm: rgb("#33609B"))]    // ✅ 用 #(...) 显式进代码模式
```

顶层写 `#active.update((thm: rgb("#33609B")))` 不受影响。
本 skill 的 prelude 把调色板放在 `soft-palette` 变量里、用 `#show: use-p` 引用，
天然绕开了这个坑——**改配色请改 `soft-palette`，不要在文档里内联写 dict**。

## 11. 一次看完所有装置

```powershell
typst compile main.typ "page-{p}.png"          # 每页一张 PNG
typst compile --pages 1-2 main.typ "head-{p}.png"
```

深色主题另出一份对照：

```typst
#show: scholia.with(theme: "dark")
```

深色主题的封面/正文底色是 `#141B27`，页面本身不透明，直接投屏或打印深色页时注意留白。

## 11. 要把 PDF 对外分发 —— 先查字体

两条链路的默认字体栈**已经是可再分发的**：STIX Two / Libertinus / 随包
`Notes Kai SC` 与 `Notes Serif SC` / Noto / Source Han / DejaVu。商业专有字体
（Optima / Avenir Next / Menlo / Songti SC / SimSun / Microsoft YaHei / Consolas）
不在生效列表里；vendored `scholia` 的 `default-fonts` 也已 patch，`note` /
`sidenote` / `label-it` 不再单独读上游商业字体。

对外分发前仍要核对一次：`pdffonts out.pdf`（poppler）或 PDF 阅读器的
「属性 → 字体」。若看到上述商业字体，说明生僻字回退到了系统字体——换一份完整
OFL 字体再排。完整口径见 [`typography-spec.md`](typography-spec.md) §1 与 §8。
