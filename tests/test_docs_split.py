# -*- coding: utf-8 -*-
"""文档拆分与市场条目归属的回归测试。

守的三件事：

1. README 是**用户向**的：安装、使用、功能、致谢；版本历史与技术细节必须在
   `CHANGELOG.md` / `docs/technical.md`，不能重新堆回 README。
2. 文档里的相对链接必须能在仓库里解析 —— 拆文件最容易留下的就是死链。
3. 插件市场条目只说「做什么 / 权限边界 / 来源」三句，点名抓取内核 `nzw806` 与
   PDF 模板 `scholia`；`8eoyw`、Typst Universe 链接、Eric Yang 与「未获背书」
   交给 `ATTRIBUTION.md` / `README.md`，市场行不再重复。
"""

import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

README = os.path.join(ROOT, "README.md")
TECHNICAL = os.path.join(ROOT, "docs", "technical.md")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
MARKET = os.path.join(
    ROOT, "market-submission", "chenqianyu486-sys__dsh-zju-lecture-note.yml"
)
ATTRIBUTION = os.path.join(ROOT, "ATTRIBUTION.md")

LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#", "tel:")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class TestMarkdownLinks(unittest.TestCase):
    """相对链接逐个落地检查。"""

    def _check(self, path):
        base = os.path.dirname(path)
        text = read(path)
        broken = []
        for target in LINK_RE.findall(text):
            if target.startswith(SKIP_PREFIXES):
                continue
            clean = target.split("#", 1)[0].strip("<>")
            if not clean:
                continue
            if not os.path.exists(os.path.join(base, clean)):
                broken.append(target)
        self.assertEqual(broken, [], f"{os.path.basename(path)} 有死链: {broken}")

    def test_readme_links_resolve(self):
        self._check(README)

    def test_technical_links_resolve(self):
        self._check(TECHNICAL)

    def test_changelog_links_resolve(self):
        self._check(CHANGELOG)


class TestReadmeStaysUserFacing(unittest.TestCase):
    def test_readme_points_at_the_detailed_docs(self):
        text = read(README)
        self.assertIn("docs/technical.md", text)
        self.assertIn("CHANGELOG.md", text)
        self.assertIn("SECURITY.md", text)
        self.assertIn("ATTRIBUTION.md", text)

    def test_readme_is_short(self):
        lines = read(README).splitlines()
        self.assertLess(
            len(lines),
            300,
            "README 又变长了（目标 300 行内），技术细节应放 docs/technical.md",
        )

    def test_version_history_moved_out(self):
        text = read(README)
        for heading in ("## 2.0.2", "## 2.0.1", "## 1.6.0", "## 1.5.1", "## 1.5.0", "## 1.4.0"):
            self.assertNotIn(heading, text)
        changelog = read(CHANGELOG)
        for heading in ("## 2.0.2", "## 2.0.1", "## 1.6.0", "## 1.5.1", "## 1.5.0", "## 1.4.0"):
            self.assertIn(heading, changelog)

    def test_technical_doc_covers_the_moved_sections(self):
        text = read(TECHNICAL)
        for token in (
            "安装形态与依赖",
            "阅读版讲义 PDF",
            "隐私设计",
            "开发与测试",
            "发布流程",
            "已知限制",
            "上游与归属",
        ):
            self.assertIn(token, text)


class TestMarketEntryAttribution(unittest.TestCase):
    """市场条目是外部读者看到的第一段话：要说清做什么，归属也不能丢。

    条目只保留「做什么 / 权限边界 / 来源」三句。静默忽略一条也没有意义——所以
    `8eoyw` 参考实现、scholia 的作者与 Typst Universe 链接改成钉在
    `ATTRIBUTION.md` 上：那里是常设致谢，市场行不必再复述一遍。
    """

    def setUp(self):
        self.text = read(MARKET)

    def test_entry_has_both_locales(self):
        self.assertIn("\n  en: ", self.text)
        self.assertIn("\n  zh: ", self.text)

    def test_scraping_core_is_named_in_the_entry(self):
        # 评审（held: author）明确要求市场条目点名抓取内核，这条不能删。
        self.assertIn("nzw806/zju-lecture-summerizer-", self.text)

    def test_entry_credits_the_pdf_template(self):
        self.assertIn("scholia", self.text)

    def test_slide_and_pdf_upstreams_stay_credited_in_attribution(self):
        attribution = read(ATTRIBUTION)
        self.assertIn("8eoyw/zju-learning-cli", attribution)
        self.assertIn("typst.app/universe/package/scholia", attribution)
        self.assertIn("Eric Yang", attribution)

    def test_no_endorsement_is_stated_in_the_readme(self):
        readme = read(README)
        self.assertIn("非官方工具", readme)
        self.assertIn("未获其背书", readme)

    def test_slide_capture_is_described_as_opt_in(self):
        # 另一条评审要求：投影截图是 opt-in 且要登录态，条目必须写。
        self.assertIn("opt-in", self.text)
        self.assertIn("插件设置中开启", self.text)


class TestMarketEntryStaysOneLine(unittest.TestCase):
    """条目是一行商品描述，不是功能清单。

    2026-11-04 按市场实际分布（en 中位数 212、p90 445；zh 中位数 84、p90 178）
    从 1226 / 561 字符压到 326 / 165。上限留了余量，只为挡住「又长回去」。
    """

    EN = re.compile(r"^  en: '(.*)'$", re.M)
    ZH = re.compile(r"^  zh: '(.*)'$", re.M)
    MAX_EN = 420
    MAX_ZH = 240

    def _value(self, pattern):
        match = pattern.search(read(MARKET))
        self.assertIsNotNone(match, "description 必须写成单行、单引号的字符串")
        return match.group(1)

    def test_description_fits_the_list_norm(self):
        self.assertLessEqual(len(self._value(self.EN)), self.MAX_EN)
        self.assertLessEqual(len(self._value(self.ZH)), self.MAX_ZH)

    def test_description_is_plain_sentences(self):
        for pattern in (self.EN, self.ZH):
            value = self._value(pattern)
            self.assertTrue(value.endswith((".", "。")), "描述要以句号结尾")
            # 条目是纯文本：README 侧会渲染成粗体，站点只做 HTML 转义，
            # `**` 会原样漏进 meta description 与卡片。
            self.assertNotIn("**", value)
            self.assertNotIn("`", value)


class TestPackaging(unittest.TestCase):
    def test_new_docs_ship_with_the_package(self):
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            package = json.load(handle)
        self.assertIn("CHANGELOG.md", package["files"])
        self.assertIn("docs/technical.md", package["files"])

    def test_mcode_package_includes_new_docs(self):
        with open(os.path.join(ROOT, "tools", "build_plugin.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('"CHANGELOG.md"', source)
        self.assertIn('"docs/technical.md"', source)


if __name__ == "__main__":
    unittest.main()
