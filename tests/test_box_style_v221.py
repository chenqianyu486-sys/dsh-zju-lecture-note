# -*- coding: utf-8 -*-
"""方框外观（v2.2.1）：标签字族、伪方框检测、讲义契约。

背景：实地会话里那份 3.5 万字讲义把 10 个例题写成 `#### 例 N：`、把证明写成
`**证明（…）**`，导出后**整页没有一个框** —— 排版器只认行首标记。同时字体补丁
把 scholia 的 `sans` 角色（方框标签 / 直觉块）换成了衬线，标签糊在正文里没有层次。

这里守住三件事：
1. 方框标签走 `sans`，且 `sans` 是可再分发的无衬线栈（不是衬线、不是 Thin 可变字体）；
2. `#### 例 N` / `**证明**` 这类「伪方框」会被检查器点名；
3. 讲义 Skill 与系统提示明确教「用标记，别用伪标题」。
"""

import io
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from zju_lecture.note_lint import check_markdown  # noqa: E402

HANDOUT = os.path.join(ROOT, "zju_lecture", "handout_prelude.typ")
VENDORED = os.path.join(
    ROOT, "zju_lecture", "typst-packages", "preview", "scholia", "0.1.0", "src"
)


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def sans_stack(text):
    block = re.search(r"sans:\s*\((.*?)\),", text, re.S)
    return block.group(1) if block else ""


class TestBoxLabelVoice(unittest.TestCase):
    """方框标签（Definition / Theorem / Your turn）用无衬线，才和正文分得开。"""

    def test_reading_template_label_is_sans(self):
        text = read(HANDOUT)
        self.assertIn('text(font: fonts.sans, weight: "bold", fill: _knot-color(tone))', text)
        self.assertIn('text(font: fonts.sans, weight: "bold", fill: palette.eg)[Your turn.]', text)

    def test_vendored_knot_label_is_sans(self):
        text = read(os.path.join(VENDORED, "theorems.typ"))
        self.assertIn('text(font: default-fonts.sans, weight: "bold", fill: a)', text)
        self.assertNotIn('text(font: default-fonts.heading, weight: "bold", fill: a)', text)
        lib = read(os.path.join(VENDORED, "lib.typ"))
        self.assertIn("default-fonts.sans, weight: \"bold\", fill: p.eg", lib)

    def test_sans_stack_is_a_real_sans_face(self):
        for path in (HANDOUT, os.path.join(VENDORED, "fonts.typ")):
            stack = sans_stack(read(path))
            self.assertIn("Noto Sans", stack, path)
            # 衬线排在 sans 第一位就等于「没有另一种声音」
            self.assertNotIn("STIX Two Text", stack, path)
            self.assertNotIn("Libertinus Serif", stack, path)

    def test_sans_stack_avoids_the_thin_variable_font(self):
        # 本机 Noto Sans SC 是可变字体，Typst 只取到 Thin（实测 pdffonts 里是
        # NotoSansSC-Thin，排出来发灰）。中文继续用随包楷体。
        for path in (HANDOUT, os.path.join(VENDORED, "fonts.typ")):
            stack = sans_stack(read(path))
            self.assertNotIn("Noto Sans SC", stack, path)
            self.assertIn("Notes Kai SC", stack, path)

    def test_vendor_patches_stay_replayable(self):
        # 补丁必须登记在 PATCHES 里，重新 vendor 时才不会被冲掉。
        text = read(os.path.join(ROOT, "tools", "vendor_typst_packages.py"))
        self.assertIn("src/theorems.typ", text)
        self.assertIn('default-fonts.sans, weight: "bold", fill: a', text)


class TestPseudoBoxIsFlagged(unittest.TestCase):
    """写成小标题/粗体的「例 N」「定理」「证明」不会变成方框。"""

    def _codes(self, text):
        return [issue.code for issue in check_markdown(text)]

    def test_example_heading_is_flagged(self):
        self.assertIn("pseudo_box", self._codes("## 一\n\n#### 例 1：用平移性质求 $x$\n"))

    def test_bold_proof_is_flagged(self):
        self.assertIn("pseudo_box", self._codes("## 一\n\n**证明（换元法）**\n"))

    def test_bold_theorem_label_is_flagged(self):
        self.assertIn("pseudo_box", self._codes("## 一\n\n**定理**：留数定理\n"))

    def test_real_marker_is_not_flagged(self):
        self.assertNotIn(
            "pseudo_box", self._codes("## 一\n\n[例] 例 1：标题 —— 正文。\n")
        )

    def test_ordinary_heading_is_not_flagged(self):
        self.assertNotIn("pseudo_box", self._codes("## 一\n\n### 定理的推广\n\n正文。\n"))


class TestContractTeachesMarkers(unittest.TestCase):
    """讲义 Skill 与系统提示必须把「标记 vs 伪标题」讲清楚。"""

    def test_skill_documents_the_anti_pattern(self):
        text = read(os.path.join(ROOT, "skills", "zju-lecture-summarizer", "SKILL.md"))
        self.assertIn("[例]", text)
        self.assertIn("#### 例 1", text)
        self.assertIn("不会", text)

    def test_system_prompt_warns_about_pseudo_boxes(self):
        text = read(os.path.join(ROOT, "lib", "index.js"))
        self.assertIn("pseudo_box", text)
        self.assertIn("[例]", text)


if __name__ == "__main__":
    unittest.main()
