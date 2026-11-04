# -*- coding: utf-8 -*-
"""左栏入口回归：``zju-lecture`` 面板同时占住侧边栏一行与 ``main`` 一页。

约束：
* 侧边栏行（``sidebar.panellist``）与它打开的页面（``main`` key）必须同 id，
  否则点击行时 ``ctx.layout.selectPanel(id)`` 找不到面板；
* 页面复用设置弹窗里的同一个组件与同一个 ``PipelineSettings`` 控制器，
  两处开关不能各写一份状态；
* 行标签走字典（``panelLabel``），图标是 ``currentColor`` 的 SVG，
  这样折叠态、选中态跟随主题；
* 页面要给 ``--dsh-frame-top-clearance`` 留位置，否则 Windows 标题栏会压住首行。
"""

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


class TestSidebarEntry(unittest.TestCase):
    """浏览器半边必须给 dsh 的左栏留一个真正的入口，而不是只在设置弹窗里。"""

    @classmethod
    def setUpClass(cls):
        cls.source = read_text("lib", "client.js")

    def test_registers_both_left_column_seats(self):
        self.assertIn("sidebar.panellist", self.source)
        self.assertIn("name: 'main'", self.source)
        self.assertIn("const PANEL_ID = 'zju-lecture'", self.source)

    def test_the_row_and_the_page_share_one_id(self):
        # 行用 id、页面用 key，两者都取自 PANEL_ID；写死两份字符串会漂移。
        self.assertNotIn("id: 'zju-lecture',\n          order: 30", self.source)
        self.assertRegex(self.source, r"name: 'main',\s*\n\s*key: PANEL_ID")
        self.assertRegex(self.source, r"name: 'sidebar\.panellist',\s*\n\s*id: PANEL_ID")

    def test_the_page_reuses_the_settings_component(self):
        self.assertIn("function SettingsPanelPage(props)", self.source)
        self.assertIn("h(PipelineSection, { ...props, asPage: true })", self.source)
        # 只有一个控制器实例：两处入口共用一个 PipelineSettings。
        self.assertEqual(self.source.count("new PipelineSettings(ctx)"), 1)

    def test_the_row_is_localized_and_ordered(self):
        self.assertIn("panelLabel", self.source)
        self.assertRegex(self.source, r"label: \(\) => t\('panelLabel'\)")
        self.assertRegex(self.source, r"name: 'sidebar\.panellist',[\s\S]{0,80}order: 30")

    def test_both_dictionaries_carry_the_new_copy(self):
        for key in ("panelLabel", "panelNote"):
            self.assertEqual(
                self.source.count(f"{key}:"),
                2,
                f"{key} 必须同时有中文与英文两份",
            )

    def test_the_page_clears_the_window_caption(self):
        self.assertIn("--dsh-frame-top-clearance", self.source)

    def test_the_glyph_follows_the_row_colour(self):
        self.assertIn("stroke: 'currentColor'", self.source)
        self.assertRegex(self.source, r"function PanelIcon\(\{ size = 18 \}\)")

    def test_smoke_reports_the_two_seats(self):
        result = subprocess.run(
            ["node", os.path.join("tests", "client_settings_smoke.mjs")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertEqual(
            payload["slots"],
            ["settings.section", "main", "sidebar.panellist"],
        )
        self.assertEqual(payload["panelKey"], payload["sidebarRow"])
        self.assertEqual(payload["sidebarRow"], payload["rowId"])
        self.assertEqual(payload["sidebarOrder"], 30)


class TestSidebarEntryDocs(unittest.TestCase):
    """README 是用户向说明：左侧栏多了一个入口，就要在这里说清楚。"""

    def test_readme_mentions_the_left_column_entry(self):
        readme = read_text("README.md")
        self.assertIn("左栏", readme)
        self.assertIn("智云讲义", readme)

    def test_technical_doc_explains_the_two_seats(self):
        doc = read_text("docs", "technical.md")
        self.assertIn("sidebar.panellist", doc)
        self.assertIn("settings.section", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
