# 排错与平台适配（实测于 Typst 0.15.1 / Windows 11）

## 1. `warning: unknown font family` 一大串 —— 可以忽略

scholia 的默认字体表里 `STIX Two Text`、`STIX Two Math`、`Optima`、`Avenir Next`、`Menlo`、
`Songti SC` 都不是 Typst 内嵌字体，Windows/Linux 上几乎必然缺失，于是编译时刷一片告警。

实测结论：**告警不影响出字**。Typst 回退到内嵌字体族，中英文都正常渲染，PDF 完整。
不要为了消告警去改文档结构。

想让观感接近官方预览：

```powershell
typst fonts   # 先看本机已有哪些字体名，名字必须与这里列出的完全一致
```

- 免费装 **STIX Two**（Text + Math，OFL）→ body/math 立刻到位。
- 标题/直觉层想要 Optima / Avenir Next 的观感，只能改 `fonts:` 覆盖成手头近似的字体。

## 2. 中文要不要加 `fonts:` 覆盖

**不用加也能出字**（已在 Windows 上实测中文标题、`note`、`theorem`、`sidenote`、封面全部正常）。

加覆盖只是为了**指定字形**，例如：

```typst
#show: scholia.with(
  theme: "light",
  fonts: (
    cjk: ("Noto Serif SC", "Source Han Serif SC", "SimSun"),
    heading: ("Microsoft YaHei", "Noto Sans SC"),
  ),
)
```

覆盖的生效范围（源码 `lib.typ` / `theorems.typ` 实测）：

| 部件 | 是否吃 `fonts:` 覆盖 |
|---|---|
| 正文、标题、页脚 | ✅ `body` / `heading` / `sans`(页脚) 生效，`cjk` 也生效 |
| 公式 | ✅ `math` 生效 |
| 行内代码 | ✅ `mono` 生效 |
| `note` / `whisper` / `TODO` | ❌ 直接读包内 `default-fonts` |
| `sidenote` | ❌ 直接读包内 `default-fonts` |
| knot 标题、`Proof.`、`label-it`、`cover` 里的 heading/sans | ❌ 直接读包内 `default-fonts` |

想让中文在 `note` 里也用指定字体，只有两条路：

1. vendor 一份包：下载 `https://packages.typst.org/preview/scholia-0.1.0.tar.gz`，解包后改
   `src/fonts.typ` 的 `cjk`（把 `("Songti SC",)` 换成你的字体栈），再从本地目录 import。
2. 接受回退字形——实测回退字形的可读性完全够用。

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

Typst 编译 PDF 时会**内嵌并子集化**用到的字体。上游默认字体表里
`Optima`、`Avenir Next`、`Menlo`、`Songti SC` 都是**商业专有字体**：
本机一旦装了并被用上，这些字体的子集就会进到 PDF 里；再把该 PDF 发给别人或公开上传，
就属于字体分发，多数商业字体 EULA 明确限制。

- **只是自己复习 / 存档**：不用管，回退到 Typst 内嵌的 Libertinus 即可。
- **要对外分发**：把字体覆盖成 `STIX Two`（SIL OFL，可自由再分发）或 Typst 内嵌字体。

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

⚠️ `fonts:` 覆盖**进不了** `note` / `sidenote` / `label-it`（这三个直接读包内 `default-fonts`），
所以只覆盖 `body` 并不能保证 PDF 里没有商业字体。要彻底可控就 vendor 包改 `src/fonts.typ`——
vendor 时**必须**把上游 `LICENSE` 与版权声明一起带上（MIT 的硬性义务），
见 [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。

检查某个 PDF 里嵌了什么字体：`pdffonts out.pdf`（poppler），或用任何 PDF 阅读器的「属性 → 字体」。
