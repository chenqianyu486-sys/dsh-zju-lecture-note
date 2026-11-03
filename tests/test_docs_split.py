# -*- coding: utf-8 -*-
"""文档拆分与市场条目归属的回归测试。

守的三件事：

1. README 是**用户向**的：安装、使用、功能、致谢；版本历史与技术细节必须在
   `CHANGELOG.md` / `docs/technical.md`，不能重新堆回 README。
2. 文档里的相对链接必须能在仓库里解析 —— 拆文件最容易留下的就是死链。
3. 插件市场条目必须点名上游：抓取内核 `nzw806`、投影参考 `8eoyw`，
   以及 PDF 模板 `scholia`（含 Typst Universe 链接）与「未获背书」声明。
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
    """市场条目是外部读者看到的第一段话，归属不能丢。"""

    def setUp(self):
        self.text = read(MARKET)

    def test_entry_has_both_locales(self):
        self.assertIn("\n  en: ", self.text)
        self.assertIn("\n  zh: ", self.text)

    def test_scraping_and_slide_upstreams_are_named(self):
        for token in ("nzw806/zju-lecture-summerizer-", "8eoyw/zju-learning-cli"):
            self.assertIn(token, self.text)

    def test_pdf_template_is_credited(self):
        self.assertIn("scholia", self.text)
        self.assertIn("typst.app/universe/package/scholia", self.text)
        self.assertIn("Eric Yang", self.text)

    def test_entry_states_no_endorsement(self):
        self.assertIn("not affiliated with or endorsed", self.text)
        self.assertIn("无隶属关系、未获背书", self.text)

    def test_slide_capture_is_described_as_opt_in(self):
        self.assertIn("opt-in", self.text)
        self.assertIn("插件设置中开启", self.text)


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
