# -*- coding: utf-8 -*-
"""v2.2.7: dsh 设置页的可用性（Agent 真实读取）与完整性。

这组测试守的是三件事：

1. **完整性**：Config 里每个用户可调字段都标了 ``.volatile()``，否则 dsh 不会把
   它投影进设置表单；设置页也必须为每个字段提供控件。
2. **可用性**：只改 volatile 字段时 dsh 不会重跑 ``apply()``，插件必须监听
   ``loader/volatile-update``，重新同步工具、Skill、提示词与 Python 子进程。
3. **版本**：九处版本号与 npm 包一致，避免发版时漏一处。
"""

import json
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPECTED_VERSION = "2.2.7"

#: dsh 设置页应当覆盖的所有字段。新增字段必须同时出现在这里、Config 与 client.js。
SETTING_FIELDS = (
    "python",
    "timeoutMs",
    "registerSkill",
    "renderPdf",
    "enableStudyNotes",
    "enableSlides",
    "embedSlideImages",
    "enableLoginTools",
    "typstAutoInstall",
    "typstPath",
    "typstMirror",
)


def read_text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def load_json(*parts):
    return json.loads(read_text(*parts))


class TestVersionAlignment(unittest.TestCase):
    def test_package_version(self):
        self.assertEqual(load_json("package.json")["version"], EXPECTED_VERSION)

    def test_other_manifests(self):
        self.assertIn(
            f'version = "{EXPECTED_VERSION}"',
            read_text("pyproject.toml"),
        )
        self.assertIn(
            f'SERVER_VERSION = "{EXPECTED_VERSION}"',
            read_text("mcp_server.py"),
        )
        self.assertEqual(load_json(".minimax-plugin", "plugin.json")["version"], EXPECTED_VERSION)
        self.assertEqual(
            load_json("adapters", "claude_code", "plugin.json")["version"],
            EXPECTED_VERSION,
        )

    def test_four_skill_manifests(self):
        for name in (
            "zju-lecture-summarizer",
            "zju-lecture-summarizer-help",
            "zju-lecture-summarizer-login",
            "scholia-notes",
        ):
            manifest = load_json("skills", f"{name}.manifest.json")
            self.assertEqual(manifest["version"], EXPECTED_VERSION, name)
            self.assertTrue(manifest["contentHash"].startswith("sha256:"), name)

    def test_package_lock_is_in_sync(self):
        lock = load_json("package-lock.json")
        self.assertEqual(lock["version"], EXPECTED_VERSION)
        self.assertEqual(lock["packages"][""]["version"], EXPECTED_VERSION)


class TestConfigCompleteness(unittest.TestCase):
    """Every user-facing setting must be visible and writable in the GUI."""

    def setUp(self):
        self.index = read_text("lib", "index.js")

    def test_every_field_is_volatile(self):
        # Slice the Config object so a `.volatile()` belonging to the next
        # field can never satisfy the regex for the current one.
        start = self.index.index("const Config = Schema.object({")
        end = self.index.index("});", start)
        block = self.index[start:end]
        for field in SETTING_FIELDS:
            self.assertIn(f"{field}:", block)
        for field in SETTING_FIELDS:
            match = re.search(rf"\n  {field}:([\s\S]*?)(?=\n  [a-zA-Z]+:|$)", block)
            self.assertIsNotNone(match, field)
            self.assertIn(".volatile()", match.group(1), f"{field} 必须可被设置页写入")
        # No field outside the expected list should drift in unnoticed.
        found = set(re.findall(r"\n  ([a-zA-Z][a-zA-Z0-9]*):", block))
        self.assertEqual(found, set(SETTING_FIELDS))

    def test_advanced_settings_have_typed_defaults(self):
        self.assertIn('python: Schema.string()', self.index)
        self.assertIn('timeoutMs: Schema.number()', self.index)
        self.assertIn('registerSkill: Schema.boolean()', self.index)
        self.assertIn('typstPath: Schema.string()', self.index)
        self.assertIn('typstMirror: Schema.string()', self.index)

    def test_client_page_has_a_control_for_every_field(self):
        client = read_text("lib", "client.js")
        for field in SETTING_FIELDS:
            self.assertIn(field, client, f"设置页没有为 {field} 提供控件")
        for ui_key in (
            "envPathTitle",
            "envMirrorTitle",
            "pythonTitle",
            "timeoutTitle",
            "registerSkillTitle",
        ):
            self.assertIn(ui_key, client)
        self.assertIn("function TextField", client)
        self.assertIn("type: 'number'", client)
        self.assertIn("min: 1000", client)
        self.assertIn("max: 900000", client)


class TestSettingsAreLive(unittest.TestCase):
    """A saved switch must reach the Agent without re-running apply()."""

    def setUp(self):
        self.index = read_text("lib", "index.js")

    def test_listens_to_volatile_updates(self):
        self.assertIn("loader/volatile-update", self.index)
        self.assertIn("ctx.on(\"loader/volatile-update\", resync)", self.index)

    def test_prompt_is_a_thunk(self):
        # A string would freeze the flags at apply() time; the thunk re-reads
        # the live refs for every prompt assembly.
        self.assertIn("text: () => buildSystemPrompt(featureFlags(config))", self.index)
        self.assertNotIn("text: buildSystemPrompt(flags)", self.index)

    def test_resync_rebuilds_children_and_registries(self):
        for needle in (
            "bridge.configure(bridgeOptions(config))",
            "syncTools()",
            "syncSkills()",
        ):
            self.assertIn(needle, self.index)
        self.assertIn("bridgeOptions(config)", self.index)

    def test_skill_switch_has_a_prompt_rule(self):
        self.assertIn("function skillFeatureRule", self.index)
        self.assertIn("registerSkill=false", self.index)
        self.assertIn("随包 Skill 未注册", self.index)

    def test_bridge_maps_typst_settings_to_environment(self):
        bridge = read_text("lib", "bridge.js")
        self.assertIn("configure(options = {})", bridge)
        self.assertIn("this.typstPath", bridge)
        self.assertIn("this.typstMirror", bridge)
        self.assertIn("env.ZJU_TYPST_BIN = this.typstPath", bridge)
        self.assertIn("env.ZJU_TYPST_MIRROR = this.typstMirror", bridge)
        # Empty fields must not wipe an inherited MCP/CLI environment.
        self.assertIn("if (this.typstPath)", bridge)
        self.assertIn("if (this.typstMirror)", bridge)

    def test_bridge_configure_changes_without_spawning(self):
        script = """
import { pathToFileURL } from 'node:url';
const { ZjuBridge } = await import(pathToFileURL(process.cwd() + '/lib/bridge.js').href);
const bridge = new ZjuBridge({ python: '', timeoutMs: 120000, enableSlides: false });
const first = bridge.configure({ python: '', timeoutMs: 120000, enableSlides: false });
const second = bridge.configure({ python: 'C:/py/python.exe', timeoutMs: 90000, enableSlides: true, typstPath: 'C:/typst/typst.exe', typstMirror: 'https://ghfast.top/' });
console.log(JSON.stringify({
  first,
  second,
  python: bridge.python,
  timeoutMs: bridge.timeoutMs,
  enableSlides: bridge.enableSlides,
  typstPath: bridge.typstPath,
  typstMirror: bridge.typstMirror,
}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertFalse(payload["first"], "unchanged configuration must not churn sessions")
        self.assertTrue(payload["second"])
        self.assertEqual(payload["python"], "C:/py/python.exe")
        self.assertEqual(payload["timeoutMs"], 90000)
        self.assertTrue(payload["enableSlides"])
        self.assertEqual(payload["typstPath"], "C:/typst/typst.exe")
        self.assertEqual(payload["typstMirror"], "https://ghfast.top/")

    def test_client_copy_does_not_promise_a_restart_for_settings(self):
        client = read_text("lib", "client.js")
        self.assertNotIn("loaded when DeepSeek Harness restarts", client)
        self.assertNotIn("完全重启 DeepSeek Harness 才按新配置加载", client)
        self.assertIn("no restart required", client)
        self.assertIn("无需重启", client)

    def test_settings_page_uses_rules_instead_of_cards(self):
        """一键配置以下改为灰色横线分组，块内设置项缩进。"""
        client = read_text("lib", "client.js")
        self.assertIn("function Group", client)
        self.assertIn("className: 'zju-groups'", client)
        self.assertIn(".zju-group + .zju-group{border-top:", client)
        self.assertIn(".zju-group-rows{padding-left:", client)
        self.assertNotIn("zju-card", client)
        self.assertNotIn("h(Card", client)
        # The page header keeps its original card frame and gradient.
        self.assertIn("background-image:linear-gradient", client)
        self.assertIn("border:1px solid var(--dsw-alias-border-l1)", client)
        self.assertIn("border-radius:14px", client)

    def test_docs_describe_live_settings(self):
        readme = read_text("README.md")
        self.assertIn("保存后**立即生效**", readme)
        self.assertIn("Typst 可执行文件", readme)
        self.assertIn("注册随包 Skill", readme)
        technical = read_text("docs", "technical.md")
        self.assertIn("loader/volatile-update", technical)
        self.assertIn("typstPath", technical)
        changelog = read_text("CHANGELOG.md")
        self.assertIn(f"## {EXPECTED_VERSION}", changelog)


class TestNodeSmokes(unittest.TestCase):
    def test_client_settings_smoke(self):
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
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(
            [field for field, _ in payload["calls"]],
            ["enableSlides", "timeoutMs", "python", "typstPath", "typstMirror", "registerSkill"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
