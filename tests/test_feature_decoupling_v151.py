# -*- coding: utf-8 -*-
"""v1.5.1 功能解耦回归：字幕主链路 vs 可选投影抓取模块。

约束：
* 投影抓取（PPT 截图）默认关闭，关闭时不注册 ``zju_fetch_slides``、
  不读取登录态、也不加载 ``zju_lecture.slides``；
* 字幕主链路（``zju_fetch_transcript`` 等）在两种模式下都必须可用；
* dsh 插件设置 ``enableSlides`` 与 MCP 环境变量 ``ZJU_ENABLE_SLIDES``
  是同一件事，不能各说各话。
"""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import mcp_server  # noqa: E402
from mcp_server import (  # noqa: E402
    TOOLS,
    SlidesDisabledError,
    available_tools,
    server_instructions,
    slides_enabled,
)

TRUTHY = ("1", "true", "YES", "on")
FALSY = ("0", "false", "OFF", "no")


def read_text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def rpc(method, request_id=1, params=None):
    return mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    })


class TestSlidesGate(unittest.TestCase):
    def test_truthy_and_falsy_env_values(self):
        for value in TRUTHY:
            with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": value}):
                self.assertTrue(slides_enabled(), value)
        for value in FALSY:
            with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": value}):
                self.assertFalse(slides_enabled(), value)

    def test_unset_env_keeps_mcp_backward_compatibility(self):
        """MCP 宿主未设置变量时保持 1.5 的行为（开启）；dsh 永远显式传 0/1。"""
        env = {key: value for key, value in os.environ.items() if key != "ZJU_ENABLE_SLIDES"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(slides_enabled())

    def test_only_the_projection_tool_is_hidden(self):
        with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": "0"}):
            names = [tool["name"] for tool in available_tools()]
        self.assertNotIn("zju_fetch_slides", names)
        self.assertEqual(
            set(names),
            {tool["name"] for tool in TOOLS} - {"zju_fetch_slides"},
        )
        for name in (
            "zju_parse_url",
            "zju_fetch_transcript",
            "zju_extract_courseware",
            "zju_check_note",
            "zju_write_note",
            "zju_get_video_url",
            "zju_read_browser_cookie",
        ):
            self.assertIn(name, names)

    def test_tools_list_and_instructions_follow_the_gate(self):
        with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": "0"}):
            names = [tool["name"] for tool in rpc("tools/list")["result"]["tools"]]
            instructions = rpc("initialize")["result"]["instructions"]
        self.assertNotIn("zju_fetch_slides", names)
        self.assertIn("投影抓取已关闭", instructions)
        self.assertIn("ZJU_ENABLE_SLIDES=1", instructions)

        with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": "1"}):
            names = [tool["name"] for tool in rpc("tools/list")["result"]["tools"]]
            instructions = rpc("initialize")["result"]["instructions"]
        self.assertIn("zju_fetch_slides", names)
        self.assertIn("投影截图", instructions)
        self.assertNotIn("投影抓取已关闭", instructions)

    def test_server_instructions_use_the_same_switch(self):
        with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": "0"}):
            self.assertIn("投影抓取已关闭", server_instructions())
        with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": "1"}):
            self.assertIn("投影截图", server_instructions())


class TestDisabledFeature(unittest.TestCase):
    def test_direct_call_raises_an_actionable_error(self):
        with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": "0"}):
            with self.assertRaises(SlidesDisabledError) as caught:
                mcp_server.handle_tool_call("zju_fetch_slides", {"url_or_sub_id": "123456"})
        message = str(caught.exception)
        self.assertIn("PPT 投影抓取未启用", message)
        self.assertIn("enableSlides", message)
        self.assertIn("ZJU_ENABLE_SLIDES=1", message)
        self.assertIn("zju_fetch_transcript", message)

    def test_rpc_call_is_reported_as_a_tool_error(self):
        with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": "0"}):
            response = rpc(
                "tools/call",
                params={"name": "zju_fetch_slides", "arguments": {"url_or_sub_id": "123456"}},
            )
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn("投影抓取未启用", result["content"][0]["text"])

    def test_enabled_call_reaches_the_auth_stage(self):
        """开关打开后，门控不再拦截，失败原因应来自登录态而不是“功能关闭”。"""
        with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": "1"}), mock.patch.object(
            mcp_server,
            "_resolve_cookie",
            return_value=(None, "测试用登录失败", None, "no_rows"),
        ):
            output = mcp_server.handle_tool_call("zju_fetch_slides", {"url_or_sub_id": "123456"})
        self.assertIn("原因: no_rows", output)
        self.assertNotIn("投影抓取未启用", output)


class TestTranscriptStaysIndependent(unittest.TestCase):
    SEGMENTS = [
        {"begin_sec": 10, "text": "各位同学大家早上好。"},
        {"begin_sec": 45, "text": "今天我们讲解霍夫曼树。"},
        {"begin_sec": 70, "text": "首先看霍夫曼编码的定义与时间复杂度。"},
    ]

    def test_transcript_still_works_when_slides_are_off(self):
        with mock.patch.dict(os.environ, {"ZJU_ENABLE_SLIDES": "0"}), mock.patch.object(
            mcp_server,
            "fetch_transcript",
            return_value=self.SEGMENTS,
        ):
            output = mcp_server.handle_tool_call(
                "zju_fetch_transcript",
                {"url_or_sub_id": "123456"},
            )
        self.assertIn("浙大智云课堂语音字幕", output)
        self.assertIn("总句数: 3", output)
        self.assertIn("霍夫曼编码", output)

    def test_transcript_only_process_never_imports_the_slides_module(self):
        code = "import sys, mcp_server; print('zju_lecture.slides' in sys.modules)"
        env = dict(os.environ)
        env.update({"ZJU_ENABLE_SLIDES": "0", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False", result.stderr)

    def test_python_package_exports_slides_lazily(self):
        code = (
            "import sys; import zju_lecture; "
            "print('before', 'zju_lecture.slides' in sys.modules); "
            "zju_lecture.download_slides; "
            "print('after', 'zju_lecture.slides' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("before False", result.stdout)
        self.assertIn("after True", result.stdout)


class TestPluginWiring(unittest.TestCase):
    def test_dsh_config_exposes_the_master_switch(self):
        source = read_text("lib", "index.js")
        self.assertIn("enableSlides", source)
        self.assertIn("registerableTools", source)
        self.assertIn("SLIDES_SKILL_FILE", source)
        self.assertIn("ZJU_ENABLE_SLIDES", read_text("lib", "bridge.js"))
        self.assertIn("ZJU_ENABLE_SLIDES", read_text("lib", "tools.js"))

    def test_mcp_config_disables_the_projection_module_by_default(self):
        with open(os.path.join(ROOT, "zju-lecture.mcp.json"), encoding="utf-8") as handle:
            config = json.load(handle)
        env = config["mcpServers"]["zju-lecture"]["env"]
        self.assertEqual(env["ZJU_ENABLE_SLIDES"], "0")
        self.assertEqual(env["ZJU_EMBED_SLIDES"], "0")
        self.assertEqual(env["ZJU_ENABLE_STUDY_NOTES"], "0")
        self.assertEqual(env["ZJU_ENABLE_LOGIN_TOOLS"], "0")
        self.assertEqual(env["ZJU_RENDER_PDF"], "0")

    def test_core_skill_is_transcript_only_and_slides_are_appended(self):
        core = read_text("skills", "zju-lecture-summarizer", "SKILL.md")
        slides = read_text("skills", "zju-lecture-summarizer", "SLIDES.md")
        self.assertNotIn("## 4. 截图入讲义", core)
        self.assertNotIn("PPT-<sub_id>.pdf", core)
        self.assertIn("zju_fetch_transcript", core)
        self.assertIn("投影抓取模块（可选附录）", slides)
        self.assertIn("PPT-<sub_id>.pdf", slides)
        self.assertIn("zju_fetch_slides", slides)

    def test_skill_manifest_tracks_both_files(self):
        with open(
            os.path.join(ROOT, "skills", "zju-lecture-summarizer.manifest.json"),
            encoding="utf-8",
        ) as handle:
            manifest = json.load(handle)
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            package = json.load(handle)
        self.assertEqual(manifest["version"], package["version"])
        paths = [item["path"] for item in manifest["files"]]
        self.assertEqual(paths, ["SKILL.md", "SLIDES.md"])
        self.assertEqual(manifest["fileCount"], 2)


class TestGuiSettingsPage(unittest.TestCase):
    """dsh 的 Config 不会自动渲染；投影开关必须由插件贡献一个浏览器设置行。"""

    def test_package_declares_the_client_half(self):
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["exports"].get("./client"), "./lib/client.js")
        client = manifest.get("dsh", {}).get("client", {})
        self.assertEqual(client.get("platform"), "web")
        self.assertTrue(client.get("immediately"))
        self.assertIn("@deepseek-ai/dsh-client-ui-settings", client.get("inject", []))
        self.assertIn(
            "@deepseek-ai/dsh-client-ui-settings-general",
            client.get("inject", []),
        )

    def test_projection_fields_are_editable_in_the_ui(self):
        """dsh-settings only projects `.volatile()` Config fields into forms."""
        source = read_text("lib", "index.js")
        for field in (
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
        ):
            self.assertRegex(
                source,
                rf"{field}:[\s\S]*?\.volatile\(\)",
                f"{field} 必须标记 .volatile()，否则不会出现在设置表单里",
            )

    def test_client_registers_a_separate_settings_section(self):
        source = read_text("lib", "client.js")
        for needle in (
            "settings.section",
            "sectionTitle",
            "configForms",
            "useEffect",
            "role: 'switch'",
            "aria-checked",
            "enableSlides",
            "embedSlideImages",
        ):
            self.assertIn(needle, source)
        self.assertNotIn("settings.general.item", source)
        self.assertIn("window.__ModuleLoader__.load", source)

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
        self.assertEqual(payload["slot"], "settings.section")
        self.assertEqual(payload["rowId"], "zju-lecture")
        self.assertEqual(payload["order"], 25)
        self.assertIn("configForms", payload["services"])
        self.assertEqual(payload["calls"][0], ["enableSlides", True])
        self.assertEqual(
            [field for field, _ in payload["calls"][1:]],
            ["timeoutMs", "python", "typstPath", "typstMirror", "registerSkill"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
