# -*- coding: utf-8 -*-
"""v2.2.4：框与证明跨段渲染（qed 落点）的回归。

守四件事：

1. **证明一直写到下一个标记/标题**：块级公式与段落都留在 ``#proof[… ]`` 里。
   旧实现遇到空行或 ``$$`` 就收尾，qed 方块停在第一段末尾 —— 实地讲义里
   看起来像「证明到这就结束了」，读者会被误导。
2. **定理/定义/例同样跨段**：陈述里的块级公式、解法的步骤列表不再甩到框外。
3. **单段装置不吸收后面的正文**：``[练习]`` / ``[边注]`` / ``[强调]`` 只吃
   标记行那一句，后面的段落仍然是正文（带段首缩进）。
4. **渲染几何**：编译出来的 PDF 里，qed 方块确实落在证明正文的最后一行，
   而不是第一行（像素 + 文本坐标双重校验；缺 poppler/Pillow 时跳过）。
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

from zju_lecture.handout import compile_handout, render_handout  # noqa: E402
from zju_lecture.study_notes import render_typst, split_review_labels  # noqa: E402

PROOF_NOTE = """## 一小节

[定理] 延迟性质 —— 若 $L[f(t)] = F(s)$，则

$$
L[f(t-t_0)u(t-t_0)] = e^{-s t_0} F(s)
$$

[证明] 直接用定义，把积分区间拆开：

$$
A = \\int_0^{+\\infty} f(t) \\mathrm{d}t
$$

令 $u = t - t_0$，则下限仍是 $0$：

$$
B = e^{-s t_0} F(s)
$$

关键是那个截断因子：不写 $u(t-t_0)$，公式就不成立。

[练习] 算一算。
"""


def _proof_fragment(typst: str) -> str:
    """截出 ``#proof[…]`` 那一段；用下一个装置/标题作右边界。"""
    start = typst.index("#proof[")
    tail = typst[start:]
    boundary = re.search(r"\n\n#(yourturn|recall|theorem|definition|example)\[|\n\n= ",
                         tail)
    return tail[: boundary.start()] if boundary else tail


class TestReadingHandoutSpans(unittest.TestCase):
    def setUp(self):
        self.rendered = render_handout(PROOF_NOTE)
        self.typst = self.rendered.typst

    def test_proof_keeps_following_math_and_paragraphs(self):
        fragment = _proof_fragment(self.typst)
        self.assertIn("直接用定义", fragment)
        self.assertIn("$ A = ", fragment)
        self.assertIn("$ B = ", fragment)
        self.assertIn("关键是那个截断因子", fragment)
        self.assertEqual(self.typst.count("#proof["), 1)

    def test_proof_ends_before_the_next_device(self):
        fragment = _proof_fragment(self.typst)
        self.assertNotIn("#yourturn", fragment)
        self.assertIn("#yourturn[算一算。", self.typst)

    def test_theorem_box_keeps_its_display_math(self):
        start = self.typst.index('#theorem("1.1"')
        end = self.typst.index("#proof[")
        fragment = self.typst[start:end]
        self.assertIn("L[f(t-t_0)u(t-t_0)]", fragment)
        self.assertIn("$", fragment)

    def test_proof_stops_at_the_next_heading(self):
        text = (
            "## 一节\n\n"
            "[证明] 直接算：\n\n$$\na = b\n$$\n\n"
            "## 二节\n\n"
            "下一节后的正文。\n"
        )
        typst = render_handout(text).typst
        proof = _proof_fragment(typst)
        self.assertIn("$ a = b $", proof)
        self.assertNotIn("下一节后的正文", proof)
        self.assertIn("#h(2em)下一节后的正文。", typst)

    def test_step_list_stays_inside_the_example_box(self):
        text = (
            "## 一节\n\n"
            "[例] 求积分 —— 用留数定理。\n\n"
            "解：分两步。\n\n"
            "- 先找奇点；\n"
            "- 再算留数。\n"
        )
        typst = render_handout(text).typst
        start = typst.index("#example(")
        fragment = typst[start:]
        self.assertIn("解：分两步。", fragment)
        self.assertIn("- 先找奇点；", fragment)
        self.assertIn("- 再算留数。", fragment)

    def test_bold_pseudo_heading_ends_the_span(self):
        # 讲义里用「整行粗体 + 时间码」当小标题；它属于下一个话题，
        # 不能被前一个例子/定理框吞进去。
        text = (
            "## 一节\n\n"
            "[例] 题面 —— 解。\n\n"
            "第一步先化简。\n\n"
            "**下一个话题** `[00:22]`\n\n"
            "[定理] 结论 —— 正文\n"
        )
        typst = render_handout(text).typst
        self.assertIn("#example(\"1.1\", title: [题面])[解。\n\n第一步先化简。]", typst)
        self.assertIn("#h(2em)*下一个话题*", typst)

    def test_review_labels_get_their_own_line(self):
        # 模型常把「题目 / 切入点 / 关键步骤 / 易错点」写进同一段；
        # 框里排成一大坨很难读，渲染时在标签前断段。
        text = (
            "## 一节\n\n"
            "[例] 题面 —— 求 $X$。题目：条件。切入点：思路。关键步骤：步骤。易错点：坑。\n"
        )
        typst = render_handout(text).typst
        for label in ("题目：条件。", "切入点：思路。", "关键步骤：步骤。", "易错点：坑。"):
            self.assertIn(label, typst)
        self.assertNotIn("求 $X$。题目：", typst)

    def test_single_line_devices_do_not_absorb(self):
        text = (
            "## 一节\n\n"
            "[练习] 题面。\n\n"
            "这一句是正文。\n\n"
            "[边注] 想一想？\n\n"
            "这一句也是正文。\n"
        )
        typst = render_handout(text).typst
        self.assertIn("#yourturn[题面。", typst)
        self.assertIn("#recall[想一想？]", typst)
        self.assertIn("#h(2em)这一句是正文。", typst)
        self.assertIn("#h(2em)这一句也是正文。", typst)

    def test_label_at_the_end_of_a_span_still_resolves(self):
        text = (
            "## 一节\n\n"
            "[定理] 留数定理 —— 正文。\n\n"
            "$$\n\\oint_C f \\, \\mathrm{d}z = 0\n$$\n\n"
            "<def:res>\n\n"
            "## 二节\n\n"
            "由 @def:res 可得。\n"
        )
        rendered = render_handout(text)
        self.assertIn("<def:res>", rendered.typst)
        self.assertIn("#link(<def:res>)[1.1]", rendered.typst)
        self.assertNotIn("\\<def:res\\>", rendered.typst)

    def test_paragraphs_inside_boxes_count_toward_the_ratio(self):
        text = (
            "## 一节\n\n"
            "[定义] a —— b\n\n[定理] c —— d\n\n[例] e —— f\n\n"
            + "\n\n".join("正文第 %d 段。" % index for index in range(8))
            + "\n"
        )
        rendered = render_handout(text)
        self.assertTrue(
            any("方框:正文" in item for item in rendered.warnings),
            rendered.warnings,
        )


class TestFillInDraftSpans(unittest.TestCase):
    def test_proof_keeps_following_math_and_paragraphs(self):
        draft = (
            "## 一节\n\n"
            "[证明] 直接用定义：\n\n$$\na = b\n$$\n\n"
            "所以成立。\n"
        )
        typst = render_typst(draft).typst
        self.assertIn("#proof[直接用定义：", typst)
        self.assertIn("$ a = b $", typst)
        self.assertIn("所以成立。]", typst)
        self.assertNotIn("#h(2em)所以成立。", typst)

    def test_knot_keeps_its_display_math(self):
        draft = (
            "## 一节\n\n"
            "[定理] 延迟性质 —— 若 $L[f] = F(s)$，则\n\n"
            "$$\nL[f(t-t_0)] = e^{-s t_0}F(s)\n$$\n"
        )
        typst = render_typst(draft).typst
        start = typst.index("#theorem[")
        fragment = typst[start:]
        self.assertIn("e^(-s t_0)F(s)", fragment)
        self.assertIn("]", fragment)

    def test_standalone_label_inside_a_span_resolves(self):
        draft = (
            "## 一节\n\n"
            "[定理] 留数定理 —— 正文。\n\n"
            "$$\n\\oint_C f \\, \\mathrm{d}z = 0\n$$\n\n"
            "<def:res>\n\n"
            "## 二节\n\n"
            "由 @def:res 可得。\n"
        )
        rendered = render_typst(draft)
        self.assertIn("<def:res>", rendered.typst)
        self.assertIn("@def:res", rendered.typst)
        self.assertIn("def:res", rendered.labels)

    def test_bold_pseudo_heading_ends_the_span(self):
        draft = (
            "## 一节\n\n"
            "[证明] 直接算：\n\n$$\na = b\n$$\n\n"
            "**下一小节** `[00:22]`\n\n"
            "下一小节的正文。\n"
        )
        typst = render_typst(draft).typst
        self.assertIn("#proof[直接算：\n\n$ a = b $]", typst)
        self.assertIn("#h(2em)*下一小节*", typst)

    def test_review_labels_get_their_own_line(self):
        draft = (
            "## 一节\n\n"
            "[例] 题面 —— 求 $X$。题目：条件。切入点：思路。关键步骤：步骤。易错点：坑。\n"
        )
        typst = render_typst(draft).typst
        self.assertIn("题目：条件。\n\n切入点：思路。", typst)
        self.assertNotIn("求 $X$。题目：", typst)

    def test_single_line_devices_stay_single(self):
        draft = (
            "## 一节\n\n"
            "[练习] 题面。\n\n"
            "这一句是正文。\n"
        )
        typst = render_typst(draft).typst
        self.assertIn("#yourturn[题面。 #workspace(n: 3)]", typst)
        self.assertIn("#h(2em)这一句是正文。", typst)

    def test_paragraph_count_includes_span_content(self):
        draft = (
            "## 一节\n\n"
            "[定理] 结论 —— 正文\n\n"
            "$$\na = b\n$$\n\n"
            "推论一段。\n"
        )
        rendered = render_typst(draft)
        self.assertGreaterEqual(rendered.paragraphs, 1)


# --------------------------------------------------------------- 渲染几何

def _poppler(name: str):
    """找真正是 Poppler 的可执行文件（Xpdf 的同名工具不支持 -bbox）。"""
    candidates = [shutil.which(name), "C:/texlive/2025/bin/windows/" + name + ".exe"]
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        try:
            done = subprocess.run(
                [candidate, "-v"], capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            continue
        output = (done.stdout or "") + (done.stderr or "")
        if "Poppler" in output:
            return candidate
    return None


def _qed_center_y(png_path: str, page_width_pt: float):
    """在右侧边注栏里找 qed 方块（thm 蓝的实心矩形），返回中心 y（pt）。"""
    from PIL import Image

    image = Image.open(png_path).convert("RGB")
    width, height = image.size
    scale = width / page_width_pt  # px / pt
    target = (0x33, 0x60, 0x9B)
    pixels = image.load()
    rows = []
    for y in range(height):
        run = 0
        for x in range(int(width * 0.7), width):
            r, g, b = pixels[x, y]
            if abs(r - target[0]) <= 10 and abs(g - target[1]) <= 10 and abs(b - target[2]) <= 10:
                run += 1
                if run >= int(6 * scale):
                    rows.append(y)
                    break
            else:
                run = 0
    if not rows:
        return None
    return (min(rows) + max(rows)) / 2 / scale


class TestReviewLabelSplitter(unittest.TestCase):
    """「题目 / 切入点 / 关键步骤 / 易错点」的断段规则。"""

    def test_splits_after_a_sentence_end(self):
        self.assertEqual(
            split_review_labels("求 X。题目：A。切入点：B。"),
            ["求 X。", "题目：A。", "切入点：B。"],
        )

    def test_keeps_labels_that_are_not_at_a_sentence_boundary(self):
        text = "这道题的题目：求值。"
        self.assertEqual(split_review_labels(text), [text])

    def test_label_at_the_start_is_not_split_again(self):
        self.assertEqual(
            split_review_labels("题目：A。切入点：B。"),
            ["题目：A。", "切入点：B。"],
        )

    def test_plain_text_is_untouched(self):
        self.assertEqual(split_review_labels("没有标签的一段话。"), ["没有标签的一段话。"])


class TestQedGeometry(unittest.TestCase):
    """qed 方块必须落在证明最后一行，而不是第一行。"""

    def test_qed_sits_on_the_last_line_of_the_proof(self):
        typst = _poppler("typst") or None
        pdftoppm = _poppler("pdftoppm")
        pdftotext = _poppler("pdftotext")
        if not (pdftoppm and pdftotext):
            self.skipTest("没有 poppler 的 pdftoppm/pdftotext")
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest("没有 Pillow")

        note = (
            "## 一节\n\n"
            "[定理] 延迟性质 —— 若 $L[f] = F(s)$，则\n\n"
            "$$\nL[f(t-t_0)u(t-t_0)] = e^{-s t_0} F(s)\n$$\n\n"
            "[证明] 直接用定义，把积分区间拆开：\n\n"
            "$$\nA = B\n$$\n\n"
            "令 $u = t - t_0$，则下限仍是 $0$，代入即可：\n\n"
            "$$\nC = D\n$$\n\n"
            "关键是那个截断因子：不写 $u(t-t_0)$，公式就不成立，证毕。\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            pdf = os.path.join(tmp, "note.pdf")
            rendered = render_handout(note, workspace_root=tmp)
            result = compile_handout(rendered.typst, pdf, workspace_root=tmp)
            if not result.ok:
                self.skipTest("编译不出 PDF：" + "；".join(result.errors))
            image_prefix = os.path.join(tmp, "page")
            subprocess.run(
                [pdftoppm, "-r", "150", "-png", "-singlefile", "-f", "1", "-l", "1",
                 pdf, image_prefix],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            square_y = _qed_center_y(image_prefix + ".png", 595.28)
            self.assertIsNotNone(square_y, "没有找到 qed 方块")
            boxes = subprocess.run(
                [pdftotext, "-f", "1", "-l", "1", "-bbox", pdf, "-"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
            ).stdout
        words = []
        for match in re.finditer(
            r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]+)</word>',
            boxes,
        ):
            words.append(
                (
                    float(match.group(1)),
                    float(match.group(2)),
                    float(match.group(3)),
                    float(match.group(4)),
                    match.group(5),
                )
            )
        proof = [word for word in words if word[4].startswith("Proof.")]
        self.assertTrue(proof, "没有找到 Proof. 标记")
        # 页脚页码在 790pt 以下；正文最后一行的 y 取页脚以上的最大值。
        body = [word for word in words if word[1] < 760]
        last = max(body, key=lambda word: word[3])
        first_y = (proof[0][1] + proof[0][3]) / 2
        last_y = (last[1] + last[3]) / 2
        # 方块在最后一行（允许 ±1 行高），而不是第一行。
        self.assertLess(abs(square_y - last_y), 18, (square_y, last_y, first_y))
        self.assertGreater(square_y, first_y + 40, (square_y, first_y))


if __name__ == "__main__":
    unittest.main()
