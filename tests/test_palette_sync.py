"""配色与字体：单一来源、对比度、可再分发性。

规范来源是 ``zju_lecture/prelude.typ`` 的 ``#let soft-palette``：
讲义模板（``handout_prelude.typ``）与 Python 侧（``handout._PALETTE``）都是
它的生成副本，``tools/sync_palette.py --check`` 负责守住三处一致。

这里再加两条规范级断言：
  * 四个强调色的对比度与文档值一致、刻度跨度（极差）1.11 ≤ 1.2；
  * 讲义模板的字体栈**默认**是 SIL OFL / Typst 内嵌字体，不把商业字体嵌进 PDF。
"""

import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zju_lecture.handout import _PALETTE  # noqa: E402

PRELUDE = os.path.join(ROOT, "zju_lecture", "prelude.typ")
HANDOUT_TYP = os.path.join(ROOT, "zju_lecture", "handout_prelude.typ")
FORMAT_SPEC = os.path.join(ROOT, "skills", "scholia-notes", "references", "format-spec.md")

#: 讲义链路用到的角色（与 tools/sync_palette.py 的 ROLES 一致）。
ROLES = ("bg", "ink", "muted", "hairline", "thm", "def", "eg", "warn", "rule", "fillin")

#: 规范里写明的对比度（对纸白 #FDFDFB）。
DOCUMENTED_CONTRAST = {
    "ink": 17.06,
    "muted": 4.49,
    "hairline": 1.31,
    "thm": 6.27,
    "def": 5.82,
    "eg": 5.25,
    "warn": 6.36,
    "rule": 2.43,
    "fillin": 2.90,
}

_ROLE_RE = re.compile(r'^\s*(?P<role>[a-z]+):\s*rgb\("(?P<hex>#[0-9A-Fa-f]{6})"\)', re.M)
_SOFT_PALETTE_RE = re.compile(r"#let soft-palette = \((?P<body>.*?)\n\)", re.S)
_TYP_PALETTE_RE = re.compile(r"#let palette = \(\n(?P<body>.*?)\n\)", re.S)
_TYP_FONTS_RE = re.compile(r"#let fonts = \((?P<body>.*?)\n\)", re.S)


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def contrast(hex_color, background="#FDFDFB"):
    """WCAG 2.x 相对亮度对比度。"""
    def luminance(value):
        value = value.lstrip("#")
        channels = [int(value[index:index + 2], 16) / 255.0 for index in (0, 2, 4)]
        linear = [
            channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = luminance(hex_color), luminance(background)
    high, low = max(first, second), min(first, second)
    return (high + 0.05) / (low + 0.05)


def palette_roles(text, pattern):
    match = pattern.search(text)
    if match is None:
        raise AssertionError("找不到 palette 块")
    return {
        item.group("role"): item.group("hex").upper()
        for item in _ROLE_RE.finditer(match.group("body"))
    }


class TestPaletteSingleSource(unittest.TestCase):
    def test_template_palette_equals_soft_palette(self):
        source = palette_roles(read_text(PRELUDE), _SOFT_PALETTE_RE)
        template = palette_roles(read_text(HANDOUT_TYP), _TYP_PALETTE_RE)
        for role in ROLES:
            self.assertEqual(
                template.get(role),
                source.get(role),
                "%s 与 prelude.typ 不一致；跑 python tools/sync_palette.py" % role,
            )

    def test_python_palette_equals_soft_palette(self):
        source = palette_roles(read_text(PRELUDE), _SOFT_PALETTE_RE)
        for role in ROLES:
            self.assertEqual(_PALETTE.get(role), source.get(role), role)

    def test_sync_tool_reports_no_drift(self):
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "sync_palette.py"), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("一致", result.stdout)

    def test_fonts_are_not_part_of_the_palette_copy(self):
        # 字体是排版参数、不是配色；同步脚本只该改 palette 块。
        template = read_text(HANDOUT_TYP)
        self.assertIn("#let fonts = (", template)
        self.assertNotIn("sync_palette", template.split("#let fonts = (")[1])


class TestPaletteContrast(unittest.TestCase):
    def test_documented_contrast_values(self):
        for role, expected in DOCUMENTED_CONTRAST.items():
            actual = contrast(_PALETTE[role])
            self.assertAlmostEqual(
                actual, expected, delta=0.02, msg="%s 的对比度与规范不符" % role
            )

    def test_accent_colors_have_similar_visual_weight(self):
        accents = [contrast(_PALETTE[role]) for role in ("thm", "def", "eg", "warn")]
        # 「极差」是对比度刻度上的跨度（6.36 − 5.25 = 1.11），不是比值。
        self.assertAlmostEqual(max(accents) - min(accents), 1.11, delta=0.02)
        self.assertLessEqual(max(accents) - min(accents), 1.2)

    def test_fillin_is_grey_and_clearly_lighter_than_ink(self):
        self.assertEqual(_PALETTE["fillin"], "#8E97A3")
        self.assertLess(contrast(_PALETTE["fillin"]), 3.0)
        self.assertLess(contrast(_PALETTE["fillin"]), contrast(_PALETTE["ink"]) / 4)

    def test_tag_and_keyword_join_the_definition_family(self):
        prelude = read_text(PRELUDE)
        self.assertIn('tag: rgb("#20705F")', prelude)
        self.assertIn('keyword: rgb("#20705F")', prelude)


class TestFontsCanBeRedistributed(unittest.TestCase):
    def setUp(self):
        self.template = read_text(HANDOUT_TYP)
        match = _TYP_FONTS_RE.search(self.template)
        self.assertIsNotNone(match, "handout_prelude.typ 里找不到 #let fonts")
        # 只看生效的行；注释里的「本机原味」不算。
        self.active = "\n".join(
            line for line in match.group("body").splitlines()
            if line.strip() and not line.strip().startswith("//")
        )

    def test_oFL_faces_come_first(self):
        self.assertRegex(self.active, r'body:\s*\(\s*"STIX Two Text"')
        self.assertRegex(self.active, r'heading:\s*\(\s*"STIX Two Text"')
        self.assertIn('"STIX Two Math"', self.template)

    def test_no_proprietary_face_in_the_default_stack(self):
        for proprietary in ("Optima", "Avenir Next", "Menlo"):
            self.assertNotIn(proprietary, self.active)

    def test_cjk_falls_back_to_oFL_fonts_first(self):
        body = self.active.split("body:", 1)[1].split("heading:", 1)[0]
        self.assertLess(body.find("Noto Serif SC"), body.find("Songti SC"))

    def test_typst_embedded_faces_are_used_as_backstop(self):
        for embedded in ("Libertinus Serif", "DejaVu Sans Mono"):
            self.assertIn(embedded, self.active)

    def test_page_is_filled_with_paper_white(self):
        self.assertIn("fill: palette.bg", self.template)


class TestFormatSpecDocumentsThePalette(unittest.TestCase):
    def setUp(self):
        self.spec = read_text(FORMAT_SPEC)

    def test_single_source_and_sync_command(self):
        self.assertIn("soft-palette", self.spec)
        self.assertIn("sync_palette.py", self.spec)

    def test_every_role_is_documented(self):
        for role in ROLES:
            self.assertIn("`%s`" % role, self.spec)
        for hex_value in (
            "#FDFDFB", "#1A1A1C", "#6F7683", "#DBDFE6", "#33609B",
            "#20705F", "#8F6218", "#6350A8", "#93A6C4", "#8E97A3",
        ):
            self.assertIn(hex_value, self.spec)


if __name__ == "__main__":
    unittest.main()
