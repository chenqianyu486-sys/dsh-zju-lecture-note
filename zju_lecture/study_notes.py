# -*- coding: utf-8 -*-
"""讲义 → 填空式学习笔记（底稿 → Typst → PDF）。

为什么单独一个模块
------------------
讲义是 Markdown，笔记是 Typst，中间夹着两次性质完全不同的转换：

1. **内容重排**：把讲义的叙述拆成「直觉 / 定义 / 定理 / 证明 / 练习 / 边注」，
   并决定哪里该挖空。这是**判断题**，属于人或模型（见 ``skills/scholia-notes/SKILL.md``
   第一阶段）。
2. **排版转换**：把受限语法的底稿翻译成 Typst 并编译。这是**计算题**，由本模块做
   （SKILL.md 第二阶段）。

本模块只做第 2 件事，所以它可以是确定的、可测的：底稿语法受限 → 转换规则固定 →
同一份底稿永远编译出同一份 PDF。

不做什么
--------
不替使用者「总结」讲义、不判断哪句是定理、不自动挖空。
自动挖空等于把「考什么」的决定权从读者/教师手里拿走，而那恰恰是这份笔记的意义。

字体与分发
----------
默认会覆盖 ``body`` / ``math`` / ``heading`` / ``sans`` 为 ``STIX Two``（SIL OFL）
或 Typst 内嵌字体，避免上游默认表里的商业专有字体（Optima / Avenir Next / Menlo /
Songti SC）子集进入可再分发的 PDF。残留风险见 ``skills/scholia-notes/SKILL.md``
「字体与分发」一节——``note`` / ``sidenote`` / ``label-it`` 直接读包内 default-fonts，
``fonts:`` 覆盖进不去，要彻底可控只能 vendor 上游包。

只依赖标准库。
"""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from itertools import count
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "StudyNotesError",
    "DraftResult",
    "RenderResult",
    "CompileResult",
    "build_draft",
    "render_typst",
    "compile_project",
    "find_typst",
    "latex_to_typst",
]


class StudyNotesError(Exception):
    """底稿/讲义不合法，或环境缺前置条件（典型是没装 Typst）。"""


# --------------------------------------------------------------------------- 常量

#: 底稿行标记 → (Typst 调用, 形态)
#:
#: 形态说明：
#:   ``single`` —— 单个内容块：``#call[内容]``
#:   ``knot``   —— 标题/来源标签/正文 的可选组合，见 :func:`_render_knot`
#:   ``none``   —— 不带内容（``[分隔]``）
MARKERS: Dict[str, Tuple[Optional[str], str]] = {
    "直觉": ("note", "single"),
    "定义": ("definition", "knot"),
    "公理": ("axiom", "knot"),
    "假设": ("assumption", "knot"),
    "记号": ("notation", "knot"),
    "定理": ("theorem", "knot"),
    "引理": ("lemma", "knot"),
    "命题": ("proposition", "knot"),
    "推论": ("corollary", "knot"),
    "例": ("example", "knot"),
    "例子": ("example", "knot"),
    "旁注": ("remark", "single"),
    "证明": ("proof", "single"),
    "练习": ("yourturn", "single"),
    "边注": ("recall", "single"),
    "边注!": ("sidenote", "single"),
    "强调": ("accent", "single"),
    "易错": ("warn", "single"),
    "弱注": ("aside", "single"),
    "触发": ("trigger", "single"),
    "分隔": (None, "none"),
}

#: 底稿里允许直接以 `#` 开头的 Typst 助手。其余的 `#` 一律转义成字面量。
TYPST_HELPERS = frozenset({
    "accent", "mark-key", "warn", "aside", "divider", "note", "definition",
    "theorem", "lemma", "proposition", "corollary", "example", "proof",
    "yourturn", "recall", "sidenote", "trigger", "remark", "TODO", "workspace",
    "label-it", "cover", "scholia", "use-palette", "fillin", "text", "emph",
    "strong", "box", "block", "table", "figure", "heading", "list",
})

#: 标题与正文之间的分隔符（长破折号优先，其次是两侧带空格的短横线）。
_KNOT_SEPARATORS = ("——", "—", " - ", " – ", " -", "- ")

#: 填空线：连续 4 个及以上下划线算一个空位。
_FILLIN_RE = re.compile(r"_{4,}")

#: 标题里手写的编号：渲染器自己编号，这里只负责剥掉。
#:
#: 两条链路共用同一套规则（阅读版从本模块 import），避免「A 剥了、B 没剥」
#: 导致同一份底稿在两种 PDF 里标题不一致。
HEADING_NUM_RES = (
    # 中文序号：一、 / （二） / 三.
    re.compile(r"^[（(]?[一二三四五六七八九十百零〇]+[）)]?[、.．,，:：)）]\s*"),
    # 带点分层的阿拉伯编号：2.1 / 2.1.3（必须整体剥掉，否则会剩一个「1」）
    re.compile(r"^\d+(?:\.\d+)+"),
    # 单层阿拉伯编号：1. / 2、 / 3（后面必须有分隔符或空格）
    re.compile(r"^\d{1,2}(?:[、.．,，:：)）]|\s+)"),
)


def strip_heading_number(title: str) -> str:
    """剥掉标题里手写的编号（``一、`` / ``1.2`` / ``3 ``）。

    渲染器会给标题自动编号；手写编号会叠成「1 1.」，见 format-spec.md §3。
    """
    for pattern in HEADING_NUM_RES:
        stripped = pattern.sub("", title, count=1)
        if stripped != title:
            return stripped.strip()
    return title

#: 每节的框（所有类型合计）上限。超过就是「滥用」——
#: 口径见 ``skills/scholia-notes/references/format-spec.md`` §2.2。
KNOT_BUDGET_PER_SECTION = 2

#: 方框 : 正文段落 的目标比值。1:8 比较稳，1:4 偏多。
KNOT_RATIO_TARGET = 8
KNOT_RATIO_TOO_MANY = 4

#: 块级公式的上下间距。**显式**给出，不让它依赖 ``par.spacing`` ——
#: 否则一调段间距，公式就会贴到上下段落上（实测直接重叠）。
EQUATION_BLOCK_SPACING = "1.6em"

#: 中文正文的排版参数（口径见 ``format-spec.md`` §1.2）：
#:
#: - **段首空两格**：用 ``#h(2em)`` 显式顶首行，**不用** ``par.first-line-indent``。
#:   Typst 只在「前一个兄弟元素是段落」时才应用首行缩进；标题后、块后、图后、
#:   公式后的段落一律不缩进（实测）。而 ``#h(2em)`` 是行内元素，
#:   放在段首就会把首行顶开两格、第二行回到版心 —— 与位置无关，处处一致。
#: - **段间距略大于行间距**（``spacing: 0.95em`` vs ``leading: 0.72em``）：
#:   段落之间比行与行之间多一点点留白，段落看得出来，但不至于让人以为换了一节。
BODY_LEADING = "0.72em"
BODY_SPACING = "0.95em"

#: 段首缩进两格的实现：行内空白顶开首行。
BODY_INDENT = "#h(2em)"

#: Typst 助手调用的开头（`#mark-key[` …）。
_HELPER_RE = re.compile(
    r"#(" + "|".join(
        sorted((re.escape(name) for name in TYPST_HELPERS), key=len, reverse=True)
    ) + r")\["
)

#: 证明骨架里的缺口标记：`[缺口: 关键那一步]`
_GAP_RE = re.compile(r"\[缺口\s*[:：]\s*([^\]]*)\]")

#: 行首标记：`[定义] …`
_MARKER_RE = re.compile(r"^\[([^\]\n]{1,8})\]\s*(.*)$")

#: 行尾原生 label：`<def:xxx>`
_LABEL_RE = re.compile(r"\s*<([A-Za-z][A-Za-z0-9_.:-]*)>\s*$")

#: 原生交叉引用：`@def:xxx`
_REF_RE = re.compile(r"@[A-Za-z][A-Za-z0-9_.:-]*")
#: 行内代码 span（`` `…` ``）。Typst 的反引号是 raw，内容原样输出。
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

#: 独占一行的公式：``$ … $``。
#:
#: Typst 只有在 ``$`` 之后有空白时，才把它当**块级公式**（居中 + 独立上下间距）；
#: 写成 ``$x$`` 的话，它只是「一行里的行内公式」—— 靠左排，还把首行缩进吃掉。
_DISPLAY_MATH_RE = re.compile(r"^\$([^$]+)\$$")

#: Markdown 有序列表 → Typst 的 ``+ ``
_OL_RE = re.compile(r"^(\s*)\d+[.)]\s+")
#: 无序列表项。`**粗体**` 不会被误判（`*` 后面紧跟的是 `*`，不是空白）。
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")

#: Markdown 表格行
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

#: Typst 注释 / 无意义空白
_BLANK_RE = re.compile(r"^\s*$")


# ------------------------------------------------------------------ LaTeX → Typst

#: LaTeX 符号 → Typst 符号（直接替换，不带参数）。
_LATEX_SYMBOLS: Dict[str, str] = {
    "cdot": "·", "times": "×", "div": "÷", "pm": "±", "mp": "∓",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥",
    "ne": "≠", "neq": "≠", "approx": "≈", "equiv": "≡", "sim": "∼",
    "propto": "∝", "in": "∈", "notin": "∉",
    "subset": "⊂", "subseteq": "⊆", "supset": "⊃", "supseteq": "⊇",
    "cup": "∪", "cap": "∩", "emptyset": "∅",
    "to": "→", "rightarrow": "→", "leftarrow": "←",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔",
    "mapsto": "↦", "infty": "∞", "partial": "∂", "nabla": "∇",
    "sum": "sum", "prod": "product", "int": "integral",
    "iint": "∬", "iiint": "∭", "oint": "∮", "coprod": "product",
    "forall": "∀", "exists": "∃", "neg": "¬", "land": "∧", "lor": "∨",
    "dots": "dots", "cdots": "dots", "ldots": "dots",
    "quad": " ", "qquad": "  ", ",": " ", ";": " ", "!": "",
    "alpha": "alpha", "beta": "beta", "gamma": "gamma", "delta": "delta",
    "epsilon": "epsilon", "varepsilon": "epsilon", "zeta": "zeta",
    "eta": "eta", "theta": "theta", "vartheta": "theta", "iota": "iota",
    "kappa": "kappa", "lambda": "lambda", "mu": "mu", "nu": "nu",
    "xi": "xi", "pi": "pi", "rho": "rho", "sigma": "sigma",
    "tau": "tau", "upsilon": "upsilon", "phi": "phi", "varphi": "phi",
    "chi": "chi", "psi": "psi", "omega": "omega",
    "Gamma": "Gamma", "Delta": "Delta", "Theta": "Theta", "Lambda": "Lambda",
    "Xi": "Xi", "Pi": "Pi", "Sigma": "Sigma", "Upsilon": "Upsilon",
    "Phi": "Phi", "Psi": "Psi", "Omega": "Omega",
    "sin": "sin", "cos": "cos", "tan": "tan", "cot": "cot",
    "log": "log", "ln": "ln", "exp": "exp", "lim": "lim",
    "det": '"det"', "dim": '"dim"', "ker": '"ker"', "deg": '"deg"',
    "gcd": '"gcd"', "arg": '"arg"', "max": '"max"', "min": '"min"',
    "sup": '"sup"', "inf": '"inf"', "Pr": '"Pr"',
    # 省略号 / 竖排省略号（Typst 的符号名与 LaTeX 不同，这里直接给字符）
    "cdots": "dots", "vdots": "⋮", "ddots": "⋱",
    # 绝对值 / 范数 / 集合分隔
    "lvert": "|", "rvert": "|", "vert": "|", "mid": "|", "Vert": "‖",
    # 花括号本身在 Typst 数学里就是字面量，直接放行
    "{": "{", "}": "}",
    # 反斜杠 + 空格：LaTeX 的显式空格（`0,\ 1,\ 2`）
    " ": " ",
    # 长箭头
    "Longrightarrow": "⟹", "Longleftarrow": "⟸", "Longleftrightarrow": "⟺",
    "implies": "⟹", "impliedby": "⟸", "iff": "⟺",
    # 复合
    "circ": "compose",
    # 定义号：Typst **没有** `triangleq` 这个符号（会报 unknown variable），
    # 只能退到 Unicode。讲义里「记作」「定义作」常用它，漏掉就整份 PDF 挂。
    "triangleq": "≙",
    # `\not` 单独走一条分支（见 latex_to_typst），这里只收它拆不动的近亲。
    "nrightarrow": "↛", "nleftarrow": "↚",
    "nRightarrow": "⇏", "nLeftarrow": "⇍", "nleftrightarrow": "↮",
    # 双曲函数
    "sinh": "sinh", "cosh": "cosh", "tanh": "tanh", "coth": "coth",
    "arcsin": "arcsin", "arccos": "arccos", "arctan": "arctan",
    # 几何 / 逻辑 / 集合杂项（用 Unicode 字符，避免依赖 Typst 的符号名）
    "square": "□", "blacksquare": "■", "checkmark": "✓", "triangle": "△",
    "ast": "∗", "star": "⋆", "bullet": "•",
    "oplus": "⊕", "otimes": "⊗", "odot": "⊙",
    "ll": "≪", "gg": "≫", "cong": "≅", "simeq": "≃",
    "preceq": "⪯", "succeq": "⪰", "leqslant": "⩽", "geqslant": "⩾",
    "setminus": "∖", "varnothing": "∅", "bigcup": "⋃", "bigcap": "⋂",
    "langle": "⟨", "rangle": "⟩",
    "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "prime": "′", "ell": "ℓ", "hbar": "ℏ", "Re": "ℜ", "Im": "ℑ",
    "angle": "∠", "degree": "°", "therefore": "∴", "because": "∵",
    # 排版开关：Typst 里没有对应物，静默去掉
    "displaystyle": "", "textstyle": "", "scriptstyle": "",
    "limits": "", "nolimits": "",
}

#: 需要一个花括号参数、且 Typst 侧同名函数的 LaTeX 命令。
_LATEX_FUNCTIONS: Dict[str, str] = {
    "overline": "overline", "underline": "underline", "hat": "hat",
    "tilde": "tilde", "bar": "bar", "vec": "vec", "dot": "dot",
    "ddot": "ddot", "widehat": "hat", "widetilde": "tilde",
}

#: 双参数函数（第一个参数是可选的根指数）。
_LATEX_FRACTIONS = ("frac", "dfrac", "tfrac", "cfrac")

#: 需要引号的多字母算子。
_LATEX_OPERATORNAME = ("operatorname", "operatorname*")

_LATEX_COMMAND_RE = re.compile(r"\\([A-Za-z]+|.)")

#: Typst 数学里已经存在的函数名：裸词直接放行，不会报 ``unknown variable``。
_TYPST_MATH_FUNCTIONS = frozenset({
    "sin", "cos", "tan", "cot", "sec", "csc",
    "sinh", "cosh", "tanh", "coth",
    "arcsin", "arccos", "arctan",
    "log", "ln", "exp", "lim", "det", "dim", "ker",
    "deg", "gcd", "arg", "max", "min", "sup", "inf", "mod", "lcm", "sgn",
})

#: 讲义里常以裸词出现的算子/缩写：转成直立文本，而不是逐字母拆开。
_TYPST_UPRIGHT_WORDS = frozenset({
    "Res", "res", "rank", "Rank", "diag", "trace", "tr", "span",
    "BVP", "IVP", "PDE", "PDEs", "ODE", "ODEs",
    "SVD", "LU", "QR", "FFT", "LHS", "RHS",
})

#: 在 Typst 数学里**可以裸写**的名字（函数 / 符号）。
#:
#: 这张表存在的唯一理由是让 :func:`latex_to_typst` **幂等**：
#: 转换器自己会产出 ``frac(…)``、``cal(L)``、``sum_(…)``、``quad``、``"Res"``，
#: 如果第二次再跑转换，这些名字会被 :func:`_plain_word` 当成「多字母变量」
#: 逐字母拆成 ``f r a c`` / ``s u m`` —— 编译报 ``unknown variable``，
#: 而 Agent 只会看到一份「莫名其妙坏掉」的公式。实测（Typst 0.15.1）这些
#: 名字裸写都能编译；``triangleq`` 不能，所以它走 Unicode。
_TYPST_BARE_NAMES = (
    _TYPST_MATH_FUNCTIONS
    | frozenset(w for w in _LATEX_SYMBOLS.values() if re.fullmatch(r"[A-Za-z]+", w))
    | frozenset({
        "frac", "sqrt", "root", "cal", "frak", "bold", "upright", "op",
        "mat", "cases", "quad", "product", "integral", "sum", "dots",
        "overbrace", "underbrace", "overline", "underline",
        "hat", "tilde", "bar", "vec", "dot", "ddot", "compose",
    })
)

#: 矩阵类环境 → Typst ``mat`` 的分隔符（``None`` 表示不画括号）。
_MATRIX_DELIMS: Dict[str, Optional[str]] = {
    "pmatrix": "(",
    "bmatrix": "[",
    "Bmatrix": "{",
    "vmatrix": "|",
    "Vmatrix": "‖",
    "matrix": None,
    "smallmatrix": None,
    "array": None,
}

#: 对齐类环境：按行拆开后用 Typst 的 ``\`` 换行 + ``&`` 对齐。
_ALIGN_ENVS = frozenset({
    "aligned", "align", "align*", "alignedat", "alignedat*",
    "gathered", "split", "multline", "multline*", "eqnarray", "eqnarray*",
})



#: Typst 侧**有对应写法**的 LaTeX 命令。
#:
#: 给 :mod:`zju_lecture.note_lint` 用：讲义里出现这张表以外的命令，说明
#: 自动排版 PDF 时这一份会整份编译失败 —— 以前这种问题只在写完 PDF 才暴露，
#: 而 Markdown 规范检查还报「通过」，两句话互相打脸。
_SUPPORTED_LATEX_COMMANDS = frozenset(
    set(_LATEX_SYMBOLS)
    | set(_LATEX_FUNCTIONS)
    | set(_LATEX_FRACTIONS)
    | set(_LATEX_OPERATORNAME)
    | set(_MATRIX_DELIMS)
    | set(_ALIGN_ENVS)
    | {
        "left", "right", "begin", "end", "sqrt", "not",
        "mathrm", "mathit", "mathsf", "mathtt", "mathbb",
        "mathcal", "mathscr", "mathfrak", "mathbf", "boldsymbol",
        "overbrace", "underbrace", "hspace",
        "text", "textbf", "textit",
    }
)


def supported_latex_commands() -> "frozenset[str]":
    """返回 Typst 侧有对应写法的 LaTeX 命令集合（不含反斜杠）。"""
    return _SUPPORTED_LATEX_COMMANDS


def _read_group(text: str, index: int) -> Tuple[Optional[str], int]:
    """从 ``index`` 处读一个花括号组。

    返回 ``(内容, 结束后的下标)``；不是 ``{`` 开头时返回 ``(None, index)``。
    """
    if index >= len(text) or text[index] != "{":
        return None, index
    depth = 0
    for pos in range(index, len(text)):
        char = text[pos]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[index + 1:pos], pos + 1
    return None, index


def _typst_script(content: str) -> str:
    """把 ``{...}`` 里的下标/上标内容变成 Typst 的 ``(...)`` 形式。

    ``a_{ij}`` 在 Typst 里必须写成 ``a_(i j)``——``ij`` 会被当成一个标识符。

    内容先递归转换一遍：``a_{n=-\\infty}`` 里的 ``\\infty`` 不转换的话，
    到 Typst 那里就是一个不认识的变量名。
    """
    text, _ = latex_to_typst(content)
    text = text.strip()
    if not text:
        return "()"
    if re.fullmatch(r"[A-Za-z]{2,}", text):
        return "(" + " ".join(text) + ")"
    # `=` 在上下标里补空格：Typst 对关系符号更宽容，但补上更稳。
    text = re.sub(r"\s*=\s*", " = ", text)
    return "(" + text + ")"


def _read_environment(
    text: str, index: int, name: str
) -> Tuple[Optional[str], int]:
    """从 ``index`` 处读取 ``\\begin{name} … \\end{name}`` 的内部文本。

    返回 ``(内部文本, 结束后的下标)``；找不到配对的 ``\\end`` 时返回
    ``(None, len(text))``。同名环境可以嵌套，所以按出现次数配平。
    """
    open_tag = "\\begin{" + name + "}"
    close_tag = "\\end{" + name + "}"
    depth = 1
    start = index
    pos = index
    while pos < len(text):
        inner_open = text.find(open_tag, pos)
        inner_close = text.find(close_tag, pos)
        if inner_close == -1:
            return None, len(text)
        if inner_open != -1 and inner_open < inner_close:
            depth += 1
            pos = inner_open + len(open_tag)
            continue
        depth -= 1
        if depth == 0:
            return text[start:inner_close], inner_close + len(close_tag)
        pos = inner_close + len(close_tag)
    return None, len(text)


def _plain_word(word: str) -> str:
    """把数学里裸写的多字母词变成 Typst 认得的写法。

    Typst 的数学模式把 ``AC`` / ``st`` / ``BVP`` 当成**未知变量**（编译直接失败），
    LaTeX 却把 ``AC`` 排成 ``A C``。规则尽量贴近 LaTeX 的原语义：

    - Typst 里能裸写的函数/符号（``sin`` / ``lim`` / ``frac`` / ``sum`` / ``cal`` …）原样放行；
    - 常见算子/缩写（``Res`` / ``diag`` / ``BVP`` …）转成直立文本；
    - 两个大写字母（``4AC`` 里的 ``AC``）按乘积拆成 ``A C``；
    - 纯小写词（``e^{-st}`` 里的 ``st``）同样逐字母拆开；
    - 其余（三个以上大写、混合大小写）按缩写处理成直立文本。

    第一条规则是**幂等**的关键：``frac``/``sum``/``quad`` 这些名字是转换器
    自己吐出来的，第二次转换必须原样放行，否则公式会被拆成一地字母。
    """
    if len(word) == 1:
        return word
    if word in _TYPST_BARE_NAMES:
        return word
    if word in _TYPST_MATH_FUNCTIONS:
        return word
    if word in _TYPST_UPRIGHT_WORDS:
        return 'upright("' + word + '")'
    if len(word) == 2 and word.isupper():
        return word[0] + " " + word[1]
    if word.islower():
        return " ".join(word)
    return 'upright("' + word + '")'


def _convert_environment(name: str, inner: str) -> Tuple[str, List[str]]:
    """把 LaTeX 环境改写成 Typst 数学。

    支持矩阵族（``pmatrix`` / ``bmatrix`` / ``Bmatrix`` / ``vmatrix`` /
    ``Vmatrix`` / ``matrix`` / ``smallmatrix`` / ``array``）、``cases``、
    对齐族（``aligned`` / ``align`` / ``gathered`` / ``split`` …）与 ``equation``。
    转不动的环境把内部内容按普通公式转换，并**点名**而不是静默丢掉。
    """
    warnings: List[str] = []
    body = re.sub(
        r"\\(?:hline|midrule|toprule|bottomrule)|\\cline\{[^}]*\}", " ", inner
    )
    body = re.sub(r"\\\\\s*\[[^\]]*\]", r"\\\\", body)  # 行距参数 `\\[2pt]`
    rows = [row.strip() for row in re.split(r"\\\\", body) if row.strip()]
    if not rows:
        return "", warnings

    def convert_cell(cell: str) -> str:
        converted, issues = latex_to_typst(cell.strip())
        warnings.extend(issues)
        return converted.strip()

    def matrix_columns() -> List[str]:
        return [", ".join(convert_cell(cell) for cell in row.split("&")) for row in rows]

    if name in _MATRIX_DELIMS:
        columns = matrix_columns()
        delimiter = _MATRIX_DELIMS[name]
        if delimiter is None:
            return "mat(delim: #none, " + "; ".join(columns) + ")", warnings
        if delimiter == "(":
            return "mat(" + "; ".join(columns) + ")", warnings
        return (
            'mat(delim: "' + delimiter + '", ' + "; ".join(columns) + ")"
        ), warnings

    if name == "cases":
        if all("&" in row for row in rows):
            entries = []
            for row in rows:
                cells = [convert_cell(cell) for cell in row.split("&")]
                entries.append(" & ".join(cells))
            return "cases(" + ", ".join(entries) + ")", warnings
        # 没有条件对齐符时退回成带左花括号的矩阵，视觉上仍然是 cases。
        return (
            'mat(delim: "{", ' + "; ".join(matrix_columns()) + ")"
        ), warnings

    if name in _ALIGN_ENVS:
        return (" \\ ").join(convert_cell(row) for row in rows), warnings

    if name in ("equation", "equation*", "math", "displaymath"):
        return convert_cell(body), warnings

    warnings.append(
        "\\begin{" + name + "}（环境未识别，内容按普通公式转换，建议手工检查）"
    )
    return convert_cell(body), warnings


def latex_to_typst(expression: str) -> Tuple[str, List[str]]:
    """把一段 LaTeX 数学改写成 Typst 数学。

    返回 ``(改写结果, 无法机械转换的片段列表)``。转换不了的**不静默丢弃**：
    它们会被列出来交给上层报告，因为「编译报错」比「悄悄改错公式」好发现得多。
    """
    warnings: List[str] = []
    out: List[str] = []
    index = 0
    length = len(expression)

    def _emit(word: str, next_index: int) -> None:
        r"""输出一个词形片段，并保证它不会和左右相邻的字母粘成一个标识符。

        Typst 把连续的字母当成一个变量（``ntheta`` / ``Abold`` 都会直接报
        unknown variable），而 LaTeX 里 ``n\theta``、``A\mathbf{x}`` 很常见。
        """
        if not word:
            return
        if out and out[-1] and out[-1][-1].isalnum():
            out.append(" ")
        out.append(word)
        if next_index < length and expression[next_index].isalnum():
            out.append(" ")

    while index < length:
        char = expression[index]

        # 引号串已经是 Typst 文本（`"Res"` / `"d"` / `upright("Re")`），原样搬运。
        # 不这么做的话，第二次转换会把 `"Res"` 里的字母再跑一遍 `_plain_word`，
        # 变成 `"upright("Res")"` —— 引号嵌套错位，编译直接挂。
        if char == '"':
            close_quote = expression.find('"', index + 1)
            if close_quote != -1:
                out.append(expression[index:close_quote + 1])
                index = close_quote + 1
                continue

        if char == "\\":
            match = _LATEX_COMMAND_RE.match(expression, index)
            if not match:
                out.append("\\")
                index += 1
                continue
            command = match.group(1)
            index = match.end()

            if command == "not":
                # `\not` 是个前缀：它否定的是**后面那个**符号。
                # 原来直接吐一个裸词 `not`，PDF 里就印成 "F(s) not → 0"，
                # 语义全反了。这里吃掉紧跟的符号换成否定的 Unicode 字符。
                negated = {
                    "=": "≠", "to": "↛", "rightarrow": "↛", "in": "∉",
                    "ni": "∌", "subset": "⊄", "supset": "⊅",
                    "equiv": "≢", "approx": "≉", "sim": "≁",
                    "le": "≰", "leq": "≰", "ge": "≱", "geq": "≱",
                    "lt": "≮", "gt": "≯", "exists": "∄",
                }
                following = _LATEX_COMMAND_RE.match(expression, index)
                if following and following.group(1) in negated:
                    _emit(negated[following.group(1)], following.end())
                    index = following.end()
                    continue
                if index < length and expression[index] in negated:
                    _emit(negated[expression[index]], index + 1)
                    index += 1
                    continue
                warnings.append("\\not")
                _emit("¬", index)
                continue

            if command in ("left", "right"):
                # `\left\{` / `\right\}` 是花括号字面量，必须保留转义。
                if index < length and expression[index] == "\\":
                    nxt = _LATEX_COMMAND_RE.match(expression, index)
                    if nxt:
                        if nxt.group(1) == "{":
                            out.append("\\{")
                        elif nxt.group(1) == "}":
                            out.append("\\}")
                        index = nxt.end()
                    else:
                        index += 1
                continue

            if command in _LATEX_FRACTIONS:
                numerator, next_index = _read_group(expression, index)
                if numerator is None:
                    warnings.append(f"\\{command}")
                    out.append(command)
                    continue
                denominator, next_index = _read_group(expression, next_index)
                if denominator is None:
                    warnings.append(f"\\{command}")
                    out.append(command)
                    index = next_index
                    continue
                _emit(f"frac({latex_to_typst(numerator)[0]}, {latex_to_typst(denominator)[0]})", next_index)
                index = next_index
                continue

            if command == "sqrt":
                root_index = index
                if root_index < length and expression[root_index] == "[":
                    close = expression.find("]", root_index)
                    if close == -1:
                        warnings.append("\\sqrt")
                        out.append("sqrt")
                        continue
                    degree = expression[root_index + 1:close]
                    radicand, next_index = _read_group(expression, close + 1)
                    if radicand is None:
                        warnings.append("\\sqrt")
                        out.append("sqrt")
                        index = next_index
                        continue
                    _emit(
                        f"root({latex_to_typst(degree)[0]}, {latex_to_typst(radicand)[0]})",
                        next_index,
                    )
                    index = next_index
                    continue
                radicand, next_index = _read_group(expression, index)
                if radicand is None:
                    warnings.append("\\sqrt")
                    out.append("sqrt")
                    continue
                _emit(f"sqrt({latex_to_typst(radicand)[0]})", next_index)
                index = next_index
                continue

            if command in _LATEX_FUNCTIONS:
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    # LaTeX 允许省略花括号：`\bar z_0`、`\vec v`。
                    # 这里连它后面的上下标一起读进来，才是 `\bar{z_0}` 的语义。
                    if index < length:
                        # 先跳过空白：`\bar z_0` 的重音作用在 z 上，不是空格上。
                        start = index
                        while start < length and expression[start].isspace():
                            start += 1
                        nxt = _LATEX_COMMAND_RE.match(expression, start)
                        base_end = nxt.end() if nxt else start + 1
                        cursor = base_end
                        while cursor < length and expression[cursor] in "_^":
                            if cursor + 1 < length and expression[cursor + 1] == "{":
                                _, after = _read_group(expression, cursor + 1)
                                if after != cursor + 1:
                                    cursor = after
                                    continue
                            cursor += 2
                        atom = expression[start:cursor]
                        _emit(
                            f"{_LATEX_FUNCTIONS[command]}({latex_to_typst(atom)[0]})",
                            cursor,
                        )
                        index = cursor
                        continue
                    warnings.append(f"\\{command}")
                    _emit(_LATEX_FUNCTIONS[command], next_index)
                    index = next_index
                    continue
                _emit(f"{_LATEX_FUNCTIONS[command]}({latex_to_typst(argument)[0]})", next_index)
                index = next_index
                continue

            if command == "text" or command == "textbf" or command == "textit":
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    warnings.append(f"\\{command}")
                    out.append("upright")
                    index = next_index
                    continue
                escaped = argument.replace('"', '\\"')
                _emit(f'upright("{escaped}")', next_index)
                index = next_index
                continue

            if command in ("mathrm", "mathit", "mathsf", "mathtt"):
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    warnings.append(f"\\{command}")
                    index = next_index
                    continue
                # 单个字母（\mathrm{d} 里的 d）直接放行：它多半是微分符号，
                # 套上 upright() 之后就没法再跟后面的字母配对了。
                if len(argument.strip()) == 1 and argument.strip().isascii() and argument.strip().isalpha():
                    # 单字母（\mathrm{d} 里的 d）用直立文本包起来：既保留微分符号的
                    # 直立字形，又不会和后面的 x 粘成未知变量 `dx`。
                    _emit('"' + argument.strip() + '"', next_index)
                else:
                    escaped = argument.replace('"', '\\"')
                    _emit(f'upright("{escaped}")', next_index)
                index = next_index
                continue

            if command == "mathbb":
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    warnings.append("\\mathbb")
                    _emit("RR", next_index)
                    index = next_index
                    continue
                mapping = {"R": "RR", "N": "NN", "Z": "ZZ", "C": "CC", "Q": "QQ"}
                _emit(mapping.get(argument.strip(), "RR"), next_index)
                index = next_index
                continue

            if command in _LATEX_OPERATORNAME:
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    warnings.append(f"\\{command}")
                    _emit('""', next_index)
                    index = next_index
                    continue
                name_text = argument.strip()
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", name_text):
                    # 算子名是裸词（rank / Res / diag）：直接进引号，别让
                    # `_plain_word` 把它改成 upright(...)。
                    _emit('"' + name_text + '"', next_index)
                else:
                    _emit('"' + latex_to_typst(name_text)[0] + '"', next_index)
                index = next_index
                continue

            if command in ("mathcal", "mathscr"):
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    warnings.append("\\" + command)
                    index = next_index
                    continue
                _emit("cal(" + latex_to_typst(argument)[0] + ")", next_index)
                index = next_index
                continue

            if command == "mathfrak":
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    warnings.append("\\mathfrak")
                    index = next_index
                    continue
                _emit("frak(" + latex_to_typst(argument)[0] + ")", next_index)
                index = next_index
                continue

            if command in ("mathbf", "boldsymbol"):
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    warnings.append("\\" + command)
                    index = next_index
                    continue
                _emit("bold(" + latex_to_typst(argument)[0] + ")", next_index)
                index = next_index
                continue

            if command in ("overbrace", "underbrace"):
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    warnings.append("\\" + command)
                    index = next_index
                    continue
                _emit(command + "(" + latex_to_typst(argument)[0] + ")", next_index)
                index = next_index
                continue

            if command == "hspace":
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    warnings.append("\\hspace")
                out.append(" ")
                index = next_index
                continue

            if command in ("begin", "end"):
                argument, next_index = _read_group(expression, index)
                if argument is None:
                    warnings.append("\\" + command)
                    index = next_index
                    continue
                name = argument.strip()
                if command == "end":
                    warnings.append("\\end{" + name + "}（多余的结束标记）")
                    index = next_index
                    continue
                if name == "array" or name.startswith("alignedat"):
                    # 紧跟环境的列格式 / 对齐点个数（`{cc}`、`{2}`），转换时忽略。
                    _, after_spec = _read_group(expression, next_index)
                    if after_spec != next_index:
                        next_index = after_spec
                inner, after = _read_environment(expression, next_index, name)
                if inner is None:
                    warnings.append(
                        "\\begin{" + name + "}（找不到配对的 \\end，内容已跳过）"
                    )
                    index = after
                    continue
                converted, issues = _convert_environment(name, inner)
                warnings.extend(issues)
                _emit(converted, after)
                index = after
                continue

            if command in _LATEX_SYMBOLS:
                symbol = _LATEX_SYMBOLS[command]
                if symbol in ("{", "}"):
                    # 花括号是字面量：左右补空格会在 `\{f(t)\}` 里留下空隙。
                    out.append(symbol)
                else:
                    _emit(symbol, index)
                continue

            warnings.append(f"\\{command}")
            _emit(command, index)
            continue

        if char.isascii() and char.isalpha():
            match = re.match(r"[A-Za-z]+", expression[index:])
            word = match.group(0) if match else char
            if len(word) == 2 and word[0] == "d":
                # 微分约定：`dz` / `dx` 在 Typst 里是未知变量，要拆成 `d z`。
                out.append("d " + word[1])
                index += 2
                continue
            out.append(_plain_word(word))
            index += len(word)
            continue

        if char == "_" or char == "^":
            if index + 1 < length and expression[index + 1] == "{":
                content, next_index = _read_group(expression, index + 1)
                if content is not None:
                    out.append(char + _typst_script(content))
                    index = next_index
                    continue
            out.append(char)
            index += 1
            continue

        out.append(char)
        index += 1

    return "".join(out), warnings


# ------------------------------------------------------------- Typst 行内转义

_PLACEHOLDER_RE = re.compile("\x00(\\d+)\x00")
_COUNTER = count()


def _protect(text: str, pattern: re.Pattern, builder) -> Tuple[str, List[Tuple[str, str]]]:
    """把 ``pattern`` 命中的片段替换成唯一占位符。

    返回 ``(替换后的文本, [(占位符, 原文)])``。占位符必须**全局唯一**：
    早先用「每轮从 0 开始编号」，结果后一轮的第一个占位符和前一轮的第一个
    撞号，恢复时会把两段内容互相顶掉。
    """
    kept: List[Tuple[str, str]] = []

    def _replace(match):
        token = "\x00{}\x00".format(next(_COUNTER))
        kept.append((token, builder(match)))
        return token

    return pattern.sub(_replace, text), kept


def _protect_helpers(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """保护 ``#mark-key[…]`` 这类助手调用（含配平的右括号）。

    只保护开括号是不够的：内容里的 ``]`` 会被后面的转义规则打散，
    助手调用就废了。
    """
    kept: List[Tuple[str, str]] = []
    out: List[str] = []
    index = 0
    length = len(text)
    while index < length:
        match = _HELPER_RE.match(text, index)
        if not match:
            out.append(text[index])
            index += 1
            continue
        cursor = match.end()
        depth = 1
        while cursor < length and depth:
            if text[cursor] == "[":
                depth += 1
            elif text[cursor] == "]":
                depth -= 1
            cursor += 1
        if depth:
            # 括号不配平：当普通文本处理，别把后面全吞掉。
            out.append(text[index])
            index += 1
            continue
        token = "\x00{}\x00".format(next(_COUNTER))
        kept.append((token, text[index:cursor]))
        out.append(token)
        index = cursor
    return "".join(out), kept


def _math_pattern() -> re.Pattern:
    return re.compile(r"\$[^$]*\$")


def _restore(text: str, kept: Sequence[Tuple[str, str]]) -> str:
    for token, value in kept:
        text = text.replace(token, value)
    return text


def escape_typst(text: str, known_labels: Optional[Sequence[str]] = None) -> str:
    """把一段 Markdown 文本转成可以直接放进 Typst markup 的形式。

    Typst 的 markup 有几个会咬人的地方，这里逐个处理：

    * ``_`` 是强调符号 → ``a_1`` 会被渲染成斜体，必须写成 ``a\\_1``；
    * ``\\`` 是转义符 → 必须双写；
    * ``[`` 会开内容块 → 底稿里的 ``[1]``（引用标记）必须写成 ``\\[1]``；
    * ``#`` 在词首会开代码模式 → 正文里的 ``C#`` 必须写成 ``C\\#``。

    已知助手的调用（``#mark-key[…]``）、数学（``$…$``）、填空线（``____``）
    与指向已知 label 的回指，先摘出来保护，免得被转义规则打散。
    """
    if not text:
        return ""

    # 行内代码优先保护：反引号里在 Typst 是 raw，**不转义才对**。
    # 此前把 `` `[00:20]` `` 转成 `` `\\[00:20\\]` ``，PDF 里就带着反斜杠念出来。
    protected, kept_code = _protect(text, _INLINE_CODE_RE, lambda m: m.group(0))
    protected, kept_math = _protect(protected, _math_pattern(), lambda m: m.group(0))
    protected, kept_helper = _protect_helpers(protected)
    protected, kept_fill = _protect(
        protected, _FILLIN_RE, lambda m: "#fillin(width: 2.2cm)"
    )

    # Markdown 的 `**粗体**` 在 Typst 里是 `*粗体*`：两边的星号直接投过去
    # 会触发 `warning: no text within stars`，加粗失效、还多一行告警。
    # 只认成对的 `**`，单个 `*` 不动（它可能是正文里的乘号或脚注）。
    protected = re.sub(r"\*\*(?!\s)([^*\n]+?)(?<!\s)\*\*", r"*\1*", protected)

    if known_labels is None:
        protected, kept_ref = _protect(protected, _REF_RE, lambda m: m.group(0))
    else:
        allowed = set(known_labels)

        def _ref_builder(match):
            name = match.group(0)[1:]
            # 指向未知 label 的回指按字面量处理：正文里的邮箱
            # （foo@example.com）不该被 Typst 当成引用而报错。
            return match.group(0) if name in allowed else "\\@"

        protected, kept_ref = _protect(protected, _REF_RE, _ref_builder)

    # 顺序要紧：先转义反斜杠本身，再转义 `_` 等字符 ——
    # 反过来会把 `_` 刚加上的那个反斜杠再转义一次，变成 `\\_`。
    protected = protected.replace("\\", "\\\\")
    protected = protected.replace("_", "\\_")
    protected = protected.replace("#", "\\#")
    protected = protected.replace("[", "\\[")
    protected = protected.replace("]", "\\]")
    protected = protected.replace("<", "\\<")
    protected = protected.replace(">", "\\>")
    protected = protected.replace("@", "\\@")

    restored = _restore(protected, kept_code)
    restored = _restore(restored, kept_math)
    restored = _restore(restored, kept_helper)
    restored = _restore(restored, kept_fill)
    restored = _restore(restored, kept_ref)
    return restored


# --------------------------------------------------------------------- 结果类型


@dataclass
class DraftResult:
    """讲义 → 填空底稿 的结果。"""

    text: str
    warnings: List[str] = field(default_factory=list)
    title: str = ""
    sections: int = 0


@dataclass
class RenderResult:
    """底稿 → Typst 的结果。

    ``paragraphs`` 与 ``devices`` 是给「格式规范检查」用的：
    正文段落数与各装置的使用次数。框（knot）多而正文少，就是「滥用框框」。
    """

    typst: str
    knots: List[Dict[str, object]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    paragraphs: int = 0
    devices: Dict[str, int] = field(default_factory=dict)

    @property
    def knot_count(self) -> int:
        return len(self.knots)

    def ratio_text(self) -> str:
        """方框 : 正文段落 的比值文本。"""
        if self.paragraphs <= 0:
            return "无正文段落"
        return f"{self.knot_count} : {self.paragraphs}"

    def ratio_is_too_many(self) -> bool:
        """比值是否超过「框框滥用」的阈值（1:4）。"""
        if self.paragraphs <= 0:
            return self.knot_count > 0
        return self.knot_count * KNOT_RATIO_TOO_MANY > self.paragraphs


@dataclass
class CompileResult:
    """Typst → PDF 的结果。"""

    ok: bool
    pdf_path: str = ""
    png_paths: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    output: str = ""


# ----------------------------------------------------------------- 底稿 → Typst


def _split_knot_parts(text: str) -> List[str]:
    """拆出标题 / 来源标签 / 正文。

    支持两种写法：

    * ``标题 | 来源标签 | 正文``（三段，竖线分隔）
    * ``标题 —— 正文``（两段，破折号分隔）

    都匹配不到时，整段当正文（此时只渲染一个内容块，等价于「没有标题」）。
    """
    if "|" in text:
        parts = [part.strip() for part in text.split("|")]
        if len(parts) == 3:
            return parts
        if len(parts) == 2:
            return [parts[0], "", parts[1]]
    for separator in _KNOT_SEPARATORS:
        if separator in text:
            head, _, tail = text.partition(separator)
            return [head.strip(), "", tail.strip()]
    return ["", "", text.strip()]


def _render_gaps(body: str, known_labels: Sequence[str]) -> str:
    """把正文里的 ``[缺口: …]`` 转成 Typst 的 ``#TODO[…]``。

    底稿里证明骨架写成 ``(i) … (ii) … [缺口: 关键那一步]``，
    排版后这一段要变成一个醒目的待填空位，而不是普通文字。
    """
    if "[缺口" not in body:
        return escape_typst(body, known_labels)
    pieces: List[str] = []
    last = 0
    for match in _GAP_RE.finditer(body):
        pieces.append(escape_typst(body[last:match.start()], known_labels))
        pieces.append("#TODO[" + escape_typst(match.group(1).strip(), known_labels) + "]")
        last = match.end()
    pieces.append(escape_typst(body[last:], known_labels))
    return "".join(pieces)


def _render_knot(call: str, body: str, known_labels: Sequence[str]) -> Tuple[str, str]:
    """渲染一个 knot 调用。

    返回 ``(Typst 片段, 抽出的 label)``。

    位置参数的语义由 frame-it 决定：**最后一个块是正文，前面的是标题与标签**。
    写成 ``#knot[a][b][c]`` 而以为 a/b 是「标题/正文」，b 会被当成来源标签
    渲染成小字，而且**不会报错** —— 所以这里严格按 arity 生成。
    """
    label = ""
    match = _LABEL_RE.search(body)
    if match:
        label = match.group(1)
        body = body[: match.start()]

    title, tag, content = _split_knot_parts(body)
    title_typst = escape_typst(title, known_labels)
    tag_typst = escape_typst(tag, known_labels)
    content_typst = _render_gaps(content, known_labels)

    if tag:
        fragment = f"#{call}[{title_typst}][{tag_typst}][{content_typst}]"
    elif title:
        fragment = f"#{call}[{title_typst}][{content_typst}]"
    else:
        fragment = f"#{call}[{content_typst}]"

    if label:
        fragment += f" <{label}>"
    return fragment, label


def _render_marker(
    marker: str,
    body: str,
    known_labels: Sequence[str],
) -> Tuple[str, str]:
    """渲染一行底稿标记。返回 ``(Typst 片段, label)``。"""
    call, shape = MARKERS[marker]

    if shape == "none":
        return "#divider", ""
    if shape == "knot":
        assert call is not None
        return _render_knot(call, body, known_labels)
    assert call is not None

    label = ""
    match = _LABEL_RE.search(body)
    if match:
        label = match.group(1)
        body = body[: match.start()]

    if call == "yourturn":
        # 练习块里的短填空线**去掉**：块里已经有 `#workspace` 的书写横线，
        # 再来几条 2.2cm 的短下划线只会挤在题面里、还折行。正文里显式写的
        # 挖空（`____`）不受影响，仍然画成灰色填空线。
        # 必须在转义**之前**处理 —— 转义会把 `____` 变成 `#fillin(…)`，
        # 那时就已经找不到下划线了。
        body = _FILLIN_RE.sub(" ", body)

    content = _render_gaps(body, known_labels)
    if call == "sidenote":
        # `sidenote` 的 symbol 必须用圆括号，方括号写法直接报 unexpected argument。
        fragment = f"#sidenote([{content}], symbol: [!])"
    elif call == "yourturn":
        fragment = f"#yourturn[{content} #workspace(n: 3)]"
    else:
        fragment = f"#{call}[{content}]"
    if label:
        fragment += f" <{label}>"
    return fragment, label


def _collapse_display_math(text: str) -> str:
    """把跨行的 ``$$ … $$`` 块压成单行 ``$ … $``。

    行级解析器一次只看一行，跨行公式会被拆散；压成单行之后
    数学段能被完整地保护起来，不会被转义规则打散。
    """
    def _replace(match: "re.Match[str]") -> str:
        inner = match.group(1).strip()
        return "$" + " ".join(inner.split()) + "$"

    return re.sub(r"\$\$(.+?)\$\$", _replace, text, flags=re.DOTALL)


#: 已经出现在 Typst 数学里的词：二次转换时遇到它们要原样放行。
_TYPST_SAFE_WORDS = (
    frozenset(w for w in _LATEX_SYMBOLS.values() if re.fullmatch(r"[A-Za-z]+", w))
    | frozenset(_LATEX_FUNCTIONS.values())
    | frozenset({
        "frac", "sqrt", "root", "mat", "cases", "cal", "frak", "bold",
        "upright", "op", "compose", "norm", "abs", "floor", "ceil", "round",
        "diag", "rank", "Res", "tr", "det", "lim", "max", "min", "sup", "inf",
    })
)


def _looks_like_typst_math(segment: str) -> bool:
    """判断一段 ``$…$`` 是不是**已经转好的** Typst 数学。

    ``build_draft`` 与 ``render_typst`` 都会调用转换器；如果第二次再把
    ``sum_(n = 1)`` 当成 LaTeX 处理，``sum`` 会被拆成 ``s u m``、``"Res"``
    会被套成 ``"upright("Res")"``。这里用「没有反斜杠、没有 ``_{``/``^{``、
    多字母词都在已知集合里」来识别 Typst，从而让转换幂等。
    """
    if "\\" in segment or "_{" in segment or "^{" in segment:
        return False
    cleaned = re.sub(r'"[^"]*"', " ", segment)
    for word in re.findall(r"[A-Za-z]+", cleaned):
        if len(word) == 1:
            continue
        if word not in _TYPST_SAFE_WORDS:
            return False
    return True


def _convert_draft_math(text: str) -> Tuple[str, List[str]]:
    """把底稿里残留的 LaTeX 数学改写成 Typst 数学。

    底稿契约是「公式写 Typst 语法」，但人（和模型）很容易顺手写成 LaTeX；
    那种情况下的编译报错是 Typst 的 ``unknown variable: sum`` 之类，
    看不出「你写的是 LaTeX」。这里在编译前先改写一遍，并把改不动的点名。

    已经是 Typst 语法的数学没有反斜杠，原样通过。
    """
    warnings: List[str] = []
    result: List[str] = []
    index = 0
    length = len(text)
    while index < length:
        if text[index] != "$":
            result.append(text[index])
            index += 1
            continue
        close = text.find("$", index + 1)
        if close == -1:
            result.append(text[index:])
            break
        inner = text[index + 1:close]
        if _looks_like_typst_math(inner):
            result.append("$" + inner + "$")
        else:
            converted, issues = latex_to_typst(inner)
            warnings.extend(issues)
            result.append("$" + converted + "$")
        index = close + 1
    return "".join(result), warnings


def _strip_html_comments(text: str) -> Tuple[str, List[str]]:
    """摘掉 HTML 注释（``<!-- … -->``），不渲染。

    底稿里可以写「只给自己看的提示」（比如「这节要不要用框？」），
    这些提示不该出现在 PDF 里，也不该被当成正文段落计数。
    """
    comments: List[str] = []

    def _replace(match: "re.Match[str]") -> str:
        comments.append(match.group(1).strip())
        return ""

    return re.sub(r"<!--(.*?)-->", _replace, text, flags=re.DOTALL), comments


def render_typst(
    draft_text: str,
    theme: str = "light",
    convert_math: bool = True,
) -> RenderResult:
    """把填空底稿渲染成完整的 ``main.typ``。

    底稿语法见 ``skills/scholia-notes/references/mapping.md``。

    ``convert_math`` 默认开启：残留的 LaTeX 数学会被改写成 Typst 数学，
    改不动的那部分会进 :attr:`RenderResult.warnings`。
    """
    if theme not in ("light", "dark"):
        raise StudyNotesError(f"theme 只能是 light / dark，收到 {theme!r}")

    knots: List[Dict[str, object]] = []
    labels: List[str] = []
    warnings: List[str] = []

    normalized = _collapse_display_math(draft_text.replace("\r\n", "\n"))
    normalized, _comments = _strip_html_comments(normalized)
    if convert_math:
        normalized, math_warnings = _convert_draft_math(normalized)
        if math_warnings:
            warnings.append(
                "底稿里还有 LaTeX 写法的数学（已尽量自动改写），以下片段无法机械转换，请手工改成 Typst 写法："
                + "、".join(sorted(set(math_warnings)))
            )

    # 第一遍：先把全文里定义过的 label 收集出来。回指只有指向这些 label 时
    # 才按 Typst 引用保留，否则正文里的邮箱会被当成引用而报错。
    known_labels = sorted({m.group(1) for m in re.finditer(r"<([A-Za-z][A-Za-z0-9_.:-]*)>", normalized)})

    section = ""
    in_cover = False
    paragraphs = 0
    devices: Dict[str, int] = {}
    lines_out: List[str] = []

    def _count(name: str) -> None:
        devices[name] = devices.get(name, 0) + 1

    # 逐行解析，但表格要一次吃完连续几行，所以用游标而不是 for。
    input_lines = normalized.split("\n")
    cursor = 0
    while cursor < len(input_lines):
        raw_line = input_lines[cursor]
        stripped = raw_line.strip()
        cursor += 1

        if not stripped:
            lines_out.append("")
            continue

        # HTML 注释在预处理阶段已经摘掉了（见 _strip_html_comments）

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = strip_heading_number(heading.group(2).strip())
            if level == 1 and title in ("封面", "Cover", "cover"):
                # 封面块由 _render_cover 单独处理：标题行与它下面的
                # `- key: value` 都不能再进正文，否则会在正文里多出一张列表。
                in_cover = True
                continue
            if in_cover:
                in_cover = False
            if level == 2:
                section = title
            lines_out.append("=" * (level - 1) + " " + escape_typst(title, known_labels))
            continue

        if in_cover:
            if re.match(r"^-\s*[A-Za-z_]+\s*:", stripped):
                continue
            in_cover = False

        marker = _MARKER_RE.match(stripped)
        if marker and (marker.group(1) in MARKERS or marker.group(1).startswith("缺口")):
            name = marker.group(1)
            body = marker.group(2)
            if name.startswith("缺口"):
                hint = body.split(":", 1)[1].strip() if ":" in body else body.strip()
                lines_out.append("#TODO[" + escape_typst(hint, known_labels) + "]")
                continue
            fragment, label = _render_marker(name, body, known_labels)
            lines_out.append(fragment)
            if label:
                labels.append(label)
            call = MARKERS[name][0]
            _count(call or name)
            if call and MARKERS[name][1] == "knot":
                knots.append({"call": call, "section": section})
            continue

        # Typst 的引用块：行首的 `>` 是引用标记，不能转义成字面量。
        if stripped.startswith(">"):
            lines_out.append(
                ">" + BODY_INDENT + escape_typst(raw_line.strip()[1:], known_labels)
            )
            _count("quote")
            continue

        # GFM 表格 → Typst `table`。底稿里保持 `| a | b |` 这种人人能读的写法，
        # 转换只发生在这一步（`build_draft` 不再产出 `#table(…)`）。
        if _TABLE_ROW_RE.match(raw_line):
            rows = [raw_line]
            while cursor < len(input_lines) and _TABLE_ROW_RE.match(input_lines[cursor]):
                rows.append(input_lines[cursor])
                cursor += 1
            lines_out.extend(_convert_table(rows, warnings))
            _count("table")
            continue

        # 无序列表：`-` / `*` / `+` 在 Typst 里统一是 `-`。
        bullet = _BULLET_RE.match(raw_line)
        if bullet:
            indent = bullet.group(1).replace("\t", "  ")
            lines_out.append(
                indent + "- " + escape_typst(bullet.group(2), known_labels)
            )
            _count("list")
            continue

        # 有序列表：Markdown 的 `1.` 在 Typst 里是 `+`（自动编号）。
        ordered = _OL_RE.match(raw_line)
        if ordered:
            indent = ordered.group(1).replace("\t", "  ")
            body = raw_line[ordered.end():].strip()
            lines_out.append(indent + "+ " + escape_typst(body, known_labels))
            _count("list")
            continue

        # 独占一行的公式：Typst 只有在 `$` 之后有空白时，才把它当**块级公式**
        # （居中 + 独立的上下间距）。写成 `$x$` 的话它只是「一行里的行内公式」，
        # 会靠左排、还把首行缩进吃掉 —— 这里补上空格。
        display = _DISPLAY_MATH_RE.match(stripped)
        if display:
            lines_out.append("$ " + display.group(1) + " $")
            _count("equation")
            continue

        # 普通段落 —— 正文的主体。段首空两格。
        lines_out.append(BODY_INDENT + escape_typst(stripped, known_labels))
        paragraphs += 1

    body_text = "\n".join(lines_out).strip()

    cover = _render_cover(normalized)
    # 中文字体族：插件自带的 Notes Kai SC（LXGW WenKai 子集，OFL）排第一，
    # 复现参考图的楷体观感；Notes Serif SC（Noto Serif SC 子集）兜底宋体。
    # 生僻字继续回退到 Noto / Source Han（OFL）；不把系统商业字体放进列表。
    cjk_fonts = (
        '"Notes Kai SC", "Notes Serif SC", "Noto Serif SC", '
        '"Source Han Serif SC"'
    )
    setup = [
        '#import "prelude.typ": *',
        f'#show: scholia.with(theme: "{theme}", prose: "notes", fonts: (cjk: ({cjk_fonts})))',
    ]
    if theme == "light":
        # 深色主题下 `use-palette` 会把内置 dark 卡覆盖回浅色，所以只给浅色用。
        setup.append("#show: use-palette")
    setup.extend([
        "",
        '#set text(lang: "zh")',
        "#set par(",
        "  justify: false,",
        f"  leading: {BODY_LEADING},",
        "  first-line-indent: 0pt,",
        f"  spacing: {BODY_SPACING},",
        ")",
        # 块级公式的上下间距显式给出：它不能跟着 par.spacing 一起变，
        # 否则一调段间距，公式就贴到上下段落上。
        "#show math.equation.where(block: true): set block("
        f"above: {EQUATION_BLOCK_SPACING}, below: {EQUATION_BLOCK_SPACING})",
        "",
    ])

    typst = "\n".join(setup) + cover + "\n\n" + body_text + "\n"

    references = sorted(set(_REF_RE.findall(normalized)))
    dangling = [ref for ref in references if ref[1:] not in known_labels]

    if dangling:
        warnings.append(
            "底稿里有找不到对应 label 的回指（编译会报错）：" + "、".join(dangling)
        )

    over_budget = _over_budget_sections(knots)
    for name, count in over_budget:
        warnings.append(
            f"第「{name}」节有 {count} 个方框，超过每节 {KNOT_BUDGET_PER_SECTION} 个的视觉预算；"
            "按格式规范，把不需要被回指的那几条降级成普通段落 + [强调] 行内强调"
        )

    result = RenderResult(
        typst=typst,
        knots=knots,
        warnings=warnings,
        labels=labels,
        references=references,
        paragraphs=paragraphs,
        devices=devices,
    )
    if result.ratio_is_too_many():
        warnings.append(
            f"方框 : 正文段落 = {result.ratio_text()}，超过 1:{KNOT_RATIO_TOO_MANY} 的红线"
            f"（目标 ≤ 1:{KNOT_RATIO_TARGET}）；这份笔记的方框盖过了正文，"
            "把非关键的那几条改成普通段落"
        )
    return result


def _over_budget_sections(knots: Sequence[Dict[str, object]]) -> List[Tuple[str, int]]:
    """统计每节的 knot 合计，返回超预算的 ``(节名, 数量)``。"""
    counts: Dict[str, int] = {}
    for knot in knots:
        name = str(knot.get("section") or "")
        counts[name] = counts.get(name, 0) + 1
    return [
        (name, count)
        for name, count in counts.items()
        if count > KNOT_BUDGET_PER_SECTION
    ]


def _render_cover(draft_text: str) -> str:
    """渲染 ``# 封面`` 块。"""
    fields: Dict[str, str] = {}
    in_cover = False
    for line in draft_text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            in_cover = level == 1 and title in ("封面", "Cover", "cover")
            continue
        if not in_cover:
            continue
        item = re.match(r"^-\s*([A-Za-z_]+)\s*:\s*(.*)$", stripped)
        if item:
            fields[item.group(1).lower()] = item.group(2).strip()

    if not fields:
        return ""

    arguments = [f'"{escape_typst(fields["title"])}"'] if fields.get("title") else ['""']
    for key in ("subtitle", "author", "date", "kicker"):
        value = fields.get(key)
        if value:
            arguments.append(f'{key}: "{escape_typst(value)}"')
    return "#cover(" + ", ".join(arguments) + ")"


# ----------------------------------------------------------------- 讲义 → 底稿


def _convert_table(rows: Sequence[str], warnings: List[str]) -> List[str]:
    """把 Markdown 表格转成 Typst 的 ``table(...)`` 调用。"""
    parsed: List[List[str]] = []
    for row in rows:
        if _TABLE_SEP_RE.match(row):
            continue
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        parsed.append(cells)
    if not parsed:
        return []
    columns = max(len(row) for row in parsed)
    lines = ["#table(", f"  columns: ({', '.join(['1fr'] * columns)}),"]
    for index, row in enumerate(parsed):
        padded = row + [""] * (columns - len(row))
        cells = ", ".join("[" + escape_typst(cell) + "]" for cell in padded)
        if index == 0:
            lines.append(f"  table.header({cells}),")
        else:
            lines.append(f"  {cells},")
    lines.append(")")
    return lines


def build_draft(
    note_text: str,
    title: str = "",
    subtitle: str = "",
    author: str = "",
    date: str = "",
    kicker: str = "",
) -> DraftResult:
    """把讲义 Markdown 变成填空底稿骨架。

    做的是**搬运**：标题层级映射、LaTeX 数学改写成 Typst 数学、
    在合适的位置插好标记位。**不做判断**：哪句是定理、哪里该挖空，
    由上层（人或模型）填 —— 所以这里留下的都是待填的占位。

    标记位按「本节有没有公式」决定密度：纯叙述章节不硬塞定理框。
    """
    warnings: List[str] = []
    normalized = note_text.replace("\r\n", "\n")
    lines = normalized.split("\n")

    doc_title = title.strip()
    body_lines: List[str] = []
    in_cover = False
    for line in lines:
        stripped = line.strip()
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            head = heading.group(2).strip()
            if level == 1 and head in ("封面", "Cover", "cover"):
                in_cover = True
                continue
            if in_cover:
                in_cover = False
            if level == 1 and not doc_title:
                doc_title = head
                continue
        if in_cover:
            continue
        body_lines.append(line)

    # 按标题切块
    blocks: List[Dict[str, object]] = []
    current: Optional[Dict[str, object]] = None
    for line in body_lines:
        heading = re.match(r"^(#{2,6})\s+(.*)$", line.strip())
        if heading:
            current = {
                "level": len(heading.group(1)),
                "title": heading.group(2).strip(),
                "lines": [],
            }
            blocks.append(current)
            continue
        if current is None:
            current = {"level": 0, "title": "", "lines": []}
            blocks.append(current)
        current["lines"].append(line)

    out: List[str] = ["# 封面"]
    out.append(f"- title: {doc_title}")
    if subtitle:
        out.append(f"- subtitle: {subtitle}")
    if author:
        out.append(f"- author: {author}")
    if date:
        out.append(f"- date: {date}")
    if kicker:
        out.append(f"- kicker: {kicker}")
    out.append("")

    for block in blocks:
        level = int(block["level"])
        block_title = str(block["title"])
        block_lines = list(block["lines"])

        if block_title:
            out.append("#" * level + " " + block_title)
            out.append("")
            if level == 2:
                out.append(f"[直觉] （用一句人话解释「{block_title}」在解决什么问题）")
                out.append("")

        has_math = any("$" in str(item) for item in block_lines)
        out.extend(_convert_block(block_lines, warnings))

        if level == 2:
            out.append("")
            if has_math:
                # 提示不渲染（HTML 注释 → 底稿里留给自己看的说明）。
                # **不替使用者插 [定义]/[定理]/[证明]**：那三个框是不是该用，
                # 取决于这条内容后面会不会被回指 —— 是内容判断，不是排版判断。
                out.append(
                    "<!-- 本节有公式：只有后面会被引用/回指的结论才用 "
                    "[定义]/[定理]/[例]（每节合计 ≤ 2 个），"
                    "其余写成普通段落，用 [强调]/[易错] 标重点。"
                    "格式规范见 references/format-spec.md -->"
                )
            # 练习块里**不插填空位**：块里本来就有书写横线，再加几条短下划线只会挤在题面里。
            out.append("[练习] （留给读者自己重做的一题）")
            out.append("[边注] （一个主动回忆问题）")
            out.append("")

    text = "\n".join(out).strip() + "\n"
    return DraftResult(
        text=text,
        warnings=warnings,
        title=doc_title,
        sections=len([block for block in blocks if int(block["level"]) == 2]),
    )


def _convert_block(lines: Sequence[str], warnings: List[str]) -> List[str]:
    """原样搬运一段正文。

    底稿的契约是**纯 Markdown + LaTeX 数学**（`references/format-spec.md` §1）：
    这里**不**把公式改写成 Typst、**不**把表格改成 ``#table(…)``、**不**把
    有序列表改成 ``+``。

    为什么曾经改过又改回来：转换只在 :func:`render_typst` 里做一次就够了。
    两处都转的话，模型按文档在底稿里继续写 LaTeX 时，第二次转换会把上一次
    已经转好的 ``frac(…)`` / ``cal(…)`` 当成多字母变量逐字母拆成 ``f r a c``、
    ``c a l`` —— 编译报 ``unknown variable``，而人看到的只是「公式莫名其妙坏了」。
    实测一次课为此白跑了 40 多个工具调用。
    """
    return list(lines)


# ------------------------------------------------------------------ 编译


_TYPST_ENV = "ZJU_TYPST_BIN"


def find_typst() -> Optional[str]:
    """找到 ``typst`` 可执行文件（含插件自举的缓存副本）。找不到返回 ``None``。

    真正的查找顺序在 :mod:`zju_lecture.deps` 里：``ZJU_TYPST_BIN`` → 插件缓存
    → PATH → 常见安装目录。这里保留同名函数，是为了不打断既有调用方与测试。
    """
    from .deps import find_typst as _find

    return _find()


def _prelude_text() -> str:
    """读取随包分发的 prelude（淡彩 palette + 五个助手）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "prelude.typ")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise StudyNotesError(f"缺少随包 prelude 文件: {path}（{exc}）") from exc


def _run_typst(typst: str, args: Sequence[str], cwd: str, timeout: int) -> Tuple[int, str]:
    try:
        completed = subprocess.run(
            [typst, *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"typst 编译超时（{timeout} 秒）。"
    except OSError as exc:
        return 127, f"无法启动 typst: {exc}"
    output = completed.stdout.decode("utf-8", errors="replace")
    return completed.returncode, output


def compile_project(
    project_dir: str,
    typst_source: str,
    make_png: bool = True,
    pages: str = "",
    timeout: int = 180,
) -> CompileResult:
    """把渲染好的 Typst 写进 ``project_dir`` 并编译。

    会生成 ``main.typ`` / ``prelude.typ`` / ``out.pdf``（以及可选的 ``page-N.png``）。
    """
    from .deps import auto_install_enabled, compile_args, probe

    info = probe(auto_install=auto_install_enabled())
    if not info.ok or not info.path:
        detail = "；".join(info.notes) if info.notes else "原因未识别"
        raise StudyNotesError(
            f"Typst 不可用（{detail}）。运行 zju_doctor(install=true) 可自动安装，"
            f"或手动安装后设置 {_TYPST_ENV}。"
        )
    typst = info.path
    shared = compile_args(project_dir)

    os.makedirs(project_dir, exist_ok=True)
    main_path = os.path.join(project_dir, "main.typ")
    prelude_path = os.path.join(project_dir, "prelude.typ")
    with open(main_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(typst_source)
    with open(prelude_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(_prelude_text())

    pdf_path = os.path.join(project_dir, "out.pdf")
    args = ["compile", *shared, "--root", project_dir, "main.typ", "out.pdf"]
    code, output = _run_typst(typst, args, project_dir, timeout)

    errors = [line for line in output.splitlines() if "error:" in line]
    warnings = [
        line for line in output.splitlines()
        if "warning:" in line and "unknown font family" not in line
    ]

    result = CompileResult(
        ok=(code == 0 and not errors),
        pdf_path=pdf_path if os.path.exists(pdf_path) else "",
        errors=errors,
        warnings=warnings,
        output=output,
    )
    if code != 0 and not errors:
        result.errors.append(f"typst 退出码 {code}（输出见下）")

    if result.ok and make_png:
        png_args = ["compile", *shared, "--root", project_dir]
        if pages:
            png_args += ["--pages", pages]
        png_args += ["main.typ", "page-{p}.png"]
        png_code, png_output = _run_typst(typst, png_args, project_dir, timeout)
        if png_code != 0:
            result.warnings.append(
                "PDF 编译成功，但逐页 PNG 导出失败（不影响 PDF）：" +
                (png_output.strip().splitlines()[-1] if png_output.strip() else f"退出码 {png_code}")
            )
        result.png_paths = sorted(
            os.path.join(project_dir, name)
            for name in os.listdir(project_dir)
            if name.startswith("page-") and name.endswith(".png")
        )

    return result
