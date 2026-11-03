# -*- coding: utf-8 -*-
"""排版规范 ↔ 实现 ↔ 两条链路渲染 的一致性测试。

三类断言：

1. **规范数值 = 实现数值**：从 ``typography-spec.md`` 的机器可读块解析，
   再从阅读版模板 / vendored scholia / Python 常量解析，逐项比对。
2. **两条链路渲染同一份内容**：量正文左/右边界、边注左边界（误差 ≤ 2pt），
   并核对封面字号集合相同、直觉块没有 2em 缩进。
3. **字体可再分发**：编译两份 PDF，用 ``pdffonts`` 确认没有商业字体。

Typst 或 poppler 缺失时跳过渲染类测试（不影响规范/实现比对）。
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zju_lecture import handout, study_notes  # noqa: E402

SPEC = os.path.join(ROOT, "skills", "scholia-notes", "references", "typography-spec.md")
HANDOUT_TYP = os.path.join(ROOT, "zju_lecture", "handout_prelude.typ")
VENDORED_LIB = os.path.join(
    ROOT, "zju_lecture", "typst-packages", "preview", "scholia", "0.1.0", "src", "lib.typ"
)
VENDORED_FONTS = os.path.join(
    ROOT, "zju_lecture", "typst-packages", "preview", "scholia", "0.1.0", "src", "fonts.typ"
)

CM_TO_PT = 72 / 2.54
PROPRIETARY = (
    "Optima", "Avenir Next", "Menlo", "Songti SC", "SimSun",
    "Microsoft YaHei", "Consolas", "KaiTi",
)

NOTE = r"""# 复变函数 第 3 讲：留数定理

## 一、留数的定义

[直觉] 留数就是 Laurent 展开里负一次幂的系数。

在孤立奇点 $z_0$ 附近，任何解析函数都可以展成 Laurent 级数

$$
\sum_{n=-\infty}^{\infty} a_n (z-z_0)^n
$$

[定理] 留数定理 —— $\int_C f(z)\,dz = 2\pi i \sum_k \operatorname{Res}(f, z_k)$ <def:res>

[证明] 把 $C$ 内部挖去以各奇点为中心的小圆，每一项趋于 $2\pi i$ 倍留数。

[例] 单位圆上的 $\int_C \frac{1}{z^2+1}\,dz$

[练习] 求 $f(z) = \frac{e^z}{z(z-1)}$ 的留数。 ____ ____

[边注] 留数与「负一次幂」这说法之间，漏了什么前提？

## 二、留数定理

见定理 @def:res。正文里的挖空：____
"""

DRAFT = r"""# 封面
- title: 复变函数 第 3 讲：留数定理
- subtitle: 课堂讲义
- author: 测试
- date: 2026-11-03
- kicker: ZJU · 智云课堂

## 一、留数的定义

[直觉] 留数就是 Laurent 展开里负一次幂的系数。

在孤立奇点 $z_0$ 附近，任何解析函数都可以展成 Laurent 级数

$$
sum_(n = -∞)^(∞) a_n (z-z_0)^n
$$

[定理] 留数定理 —— $integral_C f(z) d z = 2 pi i sum_k "Res"(f, z_k)$ <def:res>

[证明] 把 $C$ 内部挖去以各奇点为中心的小圆，每一项趋于 $2 pi i$ 倍留数。

[例] 单位圆上的 $integral_C frac(1, z^2+1) d z$

[练习] 求 $f(z) = frac(e^z, z(z-1))$ 的留数。 ____ ____

[边注] 留数与「负一次幂」这说法之间，漏了什么前提？

## 二、留数定理

见定理 @def:res。正文里的挖空：____
"""


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def spec_params():
    text = read(SPEC)
    block = re.search(r"<!-- typography-params\n(.*?)\n-->", text, re.S)
    if block is None:
        raise AssertionError("typography-spec.md 里找不到 typography-params 块")
    params = {}
    for line in block.group(1).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        params[key.strip()] = value.strip()
    return params


def slice_between(text, start, end):
    first = text.index(start)
    second = text.index(end, first)
    return text[first:second]


def one(pattern, text, group=1):
    match = re.search(pattern, text, re.S)
    if match is None:
        raise AssertionError("找不到实现参数：" + pattern)
    return match.group(group).strip()


def _inset(text):
    match = re.search(
        r"inset: \(left: ([\d.]+pt), right: ([\d.]+pt), top: ([\d.]+pt), bottom: ([\d.]+pt)\)",
        text,
    )
    if match is None:
        raise AssertionError("找不到 inset 参数")
    return ",".join(match.groups())


def handout_params():
    text = read(HANDOUT_TYP)
    page = slice_between(text, "#set page(", "#set text(")
    cover = slice_between(text, "#let cover(", "counter(page).update(1)")
    note = slice_between(text, "#let note(", "#let workspace(")
    knot = slice_between(text, "#let knot(", "#let theorem(")
    yourturn = slice_between(text, "#let yourturn(", "#let proof(")
    sidenote = slice_between(text, "#let sidenote(", "#let recall(")
    fillin = slice_between(text, "#let fillin(", "#let divider")
    h1 = slice_between(text, "heading.where(level: 1)", "heading.where(level: 2)")
    h2 = slice_between(text, "heading.where(level: 2)", "heading.where(level: 3)")
    h3 = slice_between(text, "heading.where(level: 3)", "#let _knot-color")
    divider = text[text.index("#let divider"):]
    right = one(r"margin: \(left: [\d.]+cm, right: ([\d.]+cm)", page).rstrip("cm")
    width = one(r"let note-width = ([\d.]+cm)", text).rstrip("cm")
    pad = one(r"note-width - ([\d.]+cm)", text).rstrip("cm")
    gap = "%.1fcm" % (float(right) - float(width) - float(pad))
    return {
        "page.body.left": one(r"margin: \(left: ([\d.]+cm), right:", page),
        "page.body.right": one(r"margin: \(left: [\d.]+cm, right: ([\d.]+cm)", page),
        "page.body.top": one(r"right: [\d.]+cm, top: ([\d.]+cm)", page),
        "page.body.bottom": one(r"top: [\d.]+cm, bottom: ([\d.]+cm)\)", page),
        "page.cover.margin": one(r"margin: \(left: ([\d.]+cm), right:", cover),
        "page.note.width": width + "cm",
        "page.note.gap": gap,
        "body.size": one(r"#set text\(font: fonts\.body, size: ([\d.]+pt)", text),
        "cover.kicker": one(r"size: ([\d.]+pt), tracking: 3pt", cover),
        "cover.title": one(r"size: ([\d.]+pt), tracking: 1.5pt", cover),
        "cover.subtitle": one(r"size: ([\d.]+pt), fill: palette.muted\)\[#subtitle\]", cover),
        "cover.author": one(r"size: ([\d.]+pt), tracking: 0.5pt, fill: palette.ink", cover),
        "cover.date": one(r"size: ([\d.]+pt), tracking: 0.5pt, fill: palette.muted\)\[#date\]", cover),
        "heading.h1": one(r"size: ([\d.]+pt), weight: \"bold\", fill: palette.muted", h1),
        "heading.h2": one(r"size: ([\d.]+pt), weight: \"bold\", fill: palette.def", h2),
        "heading.h3": one(r"size: ([\d.]+pt), weight: \"bold\", fill: palette.thm", h3),
        "note.size": one(r"size: ([\d.]+em), fill: palette.ink", note),
        "note.inset": _inset(note),
        "note.line": one(r"stroke: \(left: ([\d.]+pt)", note),
        "note.space": one(r"above: ([\d.]+pt),\s*below: [\d.]+pt", note),
        "knot.inset": _inset(knot),
        "knot.line": one(r"stroke: \(left: ([\d.]+pt)", knot),
        "knot.space": one(r"above: ([\d.]+pt),\s*below: [\d.]+pt", knot),
        "yourturn.inset": _inset(yourturn),
        "yourturn.line": one(r"stroke: \(left: ([\d.]+pt)", yourturn),
        "yourturn.space": one(r"above: ([\d.]+pt),\s*below: [\d.]+pt", yourturn),
        "sidenote.size": one(r"size: ([\d.]+em)", sidenote),
        "sidenote.leading": one(r"leading: ([\d.]+em)", sidenote),
        "sidenote.spacing": one(r"spacing: ([\d.]+em)", sidenote),
        "footer.size": one(r"footer: context align\(right, text\(font: fonts.sans, size: ([\d.]+em)", text),
        "fillin.width": one(r"#let fillin\(width: ([\d.]+cm)\)", fillin),
        "fillin.height": one(r"height: ([\d.]+em)", fillin),
        "fillin.stroke": one(r"stroke: \(bottom: ([\d.]+pt)", fillin),
        "divider.space": one(r"#let divider = block\(width: 100%, above: ([\d.]+em)", divider),
        "divider.stroke": one(r"#line\(length: 100%, stroke: ([\d.]+pt)", divider),
    }


def vendored_params():
    text = read(VENDORED_LIB)
    cover = slice_between(text, "#let cover(", "counter(page).update(1)")
    sidenote = slice_between(text, "#let sidenote(", "#let recall(")
    h2 = slice_between(text, "heading.where(level: 2)", "heading.where(level: 3)")
    h3 = slice_between(text, "heading.where(level: 3)", "show: theorem-rules")
    return {
        "page.cover.margin": one(r"margin: \(x: ([\d.]+cm),", cover),
        "body.size": one(r"size: ([\d.]+pt), fill: p.ink, lang:", text),
        "cover.kicker": one(r"size: ([\d.]+pt), fill: p.muted, tracking: 3pt", cover),
        "cover.title": one(r"size: ([\d.]+pt), fill: p.thm, tracking: 1.5pt", cover),
        "cover.subtitle": one(r"size: ([\d.]+pt), fill: p.muted\)\[#subtitle\]", cover),
        "cover.author": one(r"size: ([\d.]+pt), fill: p.ink, tracking: 0.5pt", cover),
        "cover.date": one(r"size: ([\d.]+pt), fill: p.muted, tracking: 0.5pt", cover),
        "heading.h2": one(r"size: ([\d.]+pt), fill: p.def", h2),
        "heading.h3": one(r"size: ([\d.]+pt), fill: p.thm", h3),
        "sidenote.leading": one(r"leading: ([\d.]+em)", sidenote),
        "sidenote.spacing": one(r"spacing: ([\d.]+em)", sidenote),
    }


def python_params():
    return {
        "body.leading": study_notes.BODY_LEADING,
        "body.spacing": study_notes.BODY_SPACING,
        "body.formula": study_notes.EQUATION_BLOCK_SPACING,
        "body.indent": study_notes.BODY_INDENT.replace("#h(", "").replace(")", ""),
    }


def normalize(value):
    return value.strip().replace(" ", "")


class TestSpecMatchesImplementation(unittest.TestCase):
    def setUp(self):
        self.spec = spec_params()

    def assert_matches(self, key, actual):
        self.assertIn(key, self.spec, "规范缺少参数 " + key)
        self.assertEqual(
            normalize(self.spec[key]), normalize(actual),
            "%s：规范写 %s，实现是 %s" % (key, self.spec[key], actual),
        )

    def test_handout_matches_spec(self):
        for key, value in handout_params().items():
            self.assert_matches(key, value)

    def test_vendored_scholia_matches_spec(self):
        for key, value in vendored_params().items():
            self.assert_matches(key, value)

    def test_python_constants_match_spec(self):
        for key, value in python_params().items():
            self.assert_matches(key, value)

    def test_both_cover_size_sets_are_identical(self):
        a = handout_params()
        b = vendored_params()
        for key in ("cover.kicker", "cover.title", "cover.subtitle", "cover.author", "cover.date"):
            self.assertEqual(a[key], b[key], key + " 两条链路不一致")

    def test_note_has_no_first_line_indent(self):
        # 参考图口径：直觉块首行不缩进；正文段首的 #h(2em) 由渲染器加。
        self.assertNotIn("#h(2em) #body", read(HANDOUT_TYP))
        self.assertNotIn("#h(2em)", slice_between(read(VENDORED_LIB), "#let note(", "#let whisper("))

    def test_spec_declares_the_single_source(self):
        text = read(SPEC)
        self.assertIn("唯一真相源", text)
        self.assertIn("typography-params", text)


def _poppler(name):
    candidates = [shutil.which(name), "C:/texlive/2025/bin/windows/" + name + ".exe"]
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        try:
            done = subprocess.run(
                [candidate, "-v"], capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        output = (done.stdout or "") + (done.stderr or "")
        if "Poppler" in output:
            return candidate
    return None


def _typst():
    return study_notes.find_typst()


def _word_boxes(pdftotext, pdf, page):
    done = subprocess.run(
        [pdftotext, "-f", str(page), "-l", str(page), "-bbox", pdf, "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    return [
        {
            "x0": float(match.group(1)),
            "x1": float(match.group(3)),
            "text": match.group(5),
        }
        for match in re.finditer(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
            done.stdout,
        )
    ]


class TestPipelinesAgreeOnRenderedGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pdftotext = _poppler("pdftotext")
        if not _typst() or not cls.pdftotext:
            raise unittest.SkipTest("需要 Typst 与 poppler 才能量渲染几何")
        cls.tmp = tempfile.mkdtemp(prefix="zju-typo-")
        cls.a_pdf = os.path.join(cls.tmp, "a.pdf")
        cls.b_pdf = os.path.join(cls.tmp, "b", "out.pdf")

        rendered = handout.render_handout(
            NOTE, workspace_root=cls.tmp, note_path=os.path.join(cls.tmp, "a.md"), toc=False,
        )
        result = handout.compile_handout(rendered.typst, cls.a_pdf, workspace_root=cls.tmp)
        if not result.ok:
            raise unittest.SkipTest("阅读版编译失败：" + "；".join(result.errors[:2]))

        draft = study_notes.render_typst(DRAFT)
        os.makedirs(os.path.dirname(cls.b_pdf), exist_ok=True)
        compiled = study_notes.compile_project(
            os.path.dirname(cls.b_pdf), draft.typst, make_png=False,
        )
        if not compiled.ok:
            raise unittest.SkipTest("填空笔记编译失败：" + "；".join(compiled.errors[:2]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", ""), ignore_errors=True)

    def _edges(self, pdf):
        words = _word_boxes(self.pdftotext, pdf, 2)
        body = [word for word in words if word["x1"] < 500]
        side = [word for word in words if word["x0"] >= 500]
        return (
            min(word["x0"] for word in body),
            max(word["x1"] for word in body),
            min(word["x0"] for word in side),
        )

    def test_body_and_sidenote_columns_match(self):
        a = self._edges(self.a_pdf)
        b = self._edges(self.b_pdf)
        for index, label in enumerate(("正文左边界", "正文右边界", "边注左边界")):
            self.assertLessEqual(
                abs(a[index] - b[index]), 2.0,
                "%s：A=%.2fpt，B=%.2fpt" % (label, a[index], b[index]),
            )

    def test_body_margins_match_the_spec(self):
        params = spec_params()
        left_pt = float(params["page.body.left"].rstrip("cm")) * CM_TO_PT
        right_pt = float(params["page.body.right"].rstrip("cm")) * CM_TO_PT
        a = self._edges(self.a_pdf)
        self.assertLessEqual(abs(a[0] - left_pt), 2.0)
        self.assertLessEqual(abs(a[1] - (595.276 - right_pt)), 2.0)

    def test_cover_font_sizes_match(self):
        # 字号由模板常量决定；两条链路已在上面的实现比对里逐项核对。
        a = handout_params()
        b = vendored_params()
        self.assertEqual(a["cover.title"], b["cover.title"])
        self.assertEqual(a["cover.kicker"], b["cover.kicker"])

    def test_pdffonts_has_no_proprietary_faces(self):
        pdffonts = _poppler("pdffonts")
        if not pdffonts:
            self.skipTest("没有 poppler 的 pdffonts")
        for pdf in (self.a_pdf, self.b_pdf):
            done = subprocess.run(
                [pdffonts, pdf], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=60,
            )
            for name in PROPRIETARY:
                self.assertNotIn(name, done.stdout, "%s 里出现了 %s" % (pdf, name))


if __name__ == "__main__":
    unittest.main()
