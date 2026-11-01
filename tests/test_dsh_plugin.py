#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dsh-zju-lecture-note 插件形态的回归测试。

覆盖：
* 生成的 dsh 工具定义与 Python 核心的 TOOLS 保持一致（防漂移）
* Node 侧导出的工具集合与 Python 侧一致
* 桥接进程能真实拉起 Python 核心并调用一次 zju_parse_url
* 插件清单 / cordis patch / Skill 的基本结构
* 隐私约定：工具 schema 中不存在 cookie / reveal / domain 一类敏感入参，
  Skill 以内存方式注册而不是复制进用户目录
"""

import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from mcp_server import TOOLS  # noqa: E402
from export_dsh_tools import build_tools, to_dsh_parameters  # noqa: E402

SENSITIVE_TOOL_PARAMS = {"cookie", "reveal", "domain", "token", "password"}


def run_node(script, *args):
    return subprocess.run(
        ["node", script, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )


def read_text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


class TestToolDefinitions(unittest.TestCase):

    def test_generated_schema_matches_python_tools(self):
        """lib/tools.schema.json 必须与当前 Python TOOLS 一致。"""
        with open(os.path.join(ROOT, "lib", "tools.schema.json"), encoding="utf-8") as handle:
            snapshot = json.load(handle)
        self.assertEqual(snapshot, build_tools())

    def test_every_mcp_tool_is_exposed(self):
        names = {tool["name"] for tool in build_tools()}
        self.assertEqual(names, {tool["name"] for tool in TOOLS})

    def test_required_flags_are_converted(self):
        parameters = to_dsh_parameters({
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
            "required": ["a"],
        })
        self.assertTrue(parameters["a"].get("required"))
        self.assertNotIn("required", parameters["b"])

    def test_unsupported_json_schema_keywords_are_stripped(self):
        """dsh defineTool rejects keywords such as `minimum` at registration."""
        parameters = to_dsh_parameters({
            "type": "object",
            "properties": {
                "n": {"type": "integer", "minimum": 0, "maximum": 10, "default": 3},
            },
        })
        self.assertEqual(parameters["n"], {"type": "integer", "default": 3})
        for tool in build_tools():
            for schema in tool["parameters"].values():
                for unsupported in ("minimum", "maximum", "pattern", "minLength", "maxLength"):
                    self.assertNotIn(unsupported, schema, tool["name"])

    def test_plugin_apply_smoke_against_real_dsh_packages(self):
        """apply() must register tools/skill/prompt with the real dsh packages."""
        result = run_node(os.path.join("tests", "plugin_apply_smoke.mjs"))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertTrue(payload.get("ok"), payload)
        if not payload.get("skipped"):
            self.assertEqual(len(payload["tools"]), len(TOOLS))
            self.assertEqual(payload["skill"], "zju-lecture-summarizer")
            self.assertIn("123456", payload["result"])

    def test_node_exports_the_same_tools(self):
        result = run_node(
            "-e",
            "import('./lib/tools.js').then(m => console.log(JSON.stringify(m.ZJU_TOOLS.map(t => t.name))))",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        names = json.loads(result.stdout.strip())
        self.assertEqual(set(names), {tool["name"] for tool in TOOLS})


class TestNoSecretToolInputs(unittest.TestCase):
    """A login cookie must never be a model-visible tool argument."""

    def test_tool_schemas_expose_no_secret_parameters(self):
        for tool in TOOLS:
            properties = tool["inputSchema"].get("properties", {})
            for forbidden in SENSITIVE_TOOL_PARAMS:
                self.assertNotIn(
                    forbidden,
                    properties,
                    f"{tool['name']} 暴露了敏感入参 {forbidden}",
                )

    def test_dsh_tool_definitions_expose_no_secret_parameters(self):
        for tool in build_tools():
            for forbidden in SENSITIVE_TOOL_PARAMS:
                self.assertNotIn(forbidden, tool["parameters"], tool["name"])

    def test_descriptions_do_not_promise_plaintext_cookie_echo(self):
        for tool in TOOLS:
            self.assertNotIn("reveal=true", tool["description"])
            self.assertNotIn("回显 Cookie 明文", tool["description"])


class TestBridge(unittest.TestCase):

    def test_bridge_calls_the_python_core(self):
        result = run_node(os.path.join("tests", "bridge_smoke.mjs"))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertTrue(payload.get("ok"), payload)
        self.assertIn("123456", payload["result"])
        self.assertEqual(payload["tools"], len(TOOLS))

    def test_bridge_turns_mcp_is_error_into_a_throw(self):
        """MCP 的 isError 必须冒泡成异常，否则失败在宿主里显示为成功。"""
        result = run_node(os.path.join("tests", "bridge_error_smoke.mjs"))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertTrue(payload.get("ok"), payload)
        self.assertIn("sub_id", payload["message"])

    def test_bridge_forwards_the_session_workspace(self):
        """P1-1：相对路径必须能在会话工作区里解析到（而不是子进程 cwd）。"""
        result = run_node(os.path.join("tests", "bridge_workspace_smoke.mjs"))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(
            os.path.normcase(payload["spawnedWorkspace"]),
            os.path.normcase(payload["workspace"]),
            "Python 子进程没有在 session workspace 里启动",
        )
        self.assertTrue(payload["errorListsCandidates"], payload)


class TestPackage(unittest.TestCase):

    def test_manifest_declares_the_dsh_bundle(self):
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["name"], "dsh-zju-lecture-note")
        self.assertEqual(manifest["version"], "1.4.2")
        self.assertEqual(manifest["type"], "module")
        self.assertEqual(manifest["icon"], "icon.png")
        self.assertEqual(manifest["dsh"]["bundle"]["patch"], "./cordis.patch.yml")
        self.assertIn("mcp_server.py", manifest["files"])
        self.assertIn("zju_lecture/*.py", manifest["files"])
        # 必须逐文件枚举：files 里写整个 "zju_lecture" 目录会把 __pycache__/*.pyc 打进包
        # （files 字段的优先级高于 .npmignore）。
        self.assertNotIn("zju_lecture", manifest["files"])
        self.assertIn("skills/zju-lecture-summarizer", manifest["files"])
        self.assertIn("SECURITY.md", manifest["files"])
        self.assertIn("@deepseek-ai/dsh-tools", manifest["peerDependencies"])
        # 隐私：不要声明用不到的 peer，减少版本不匹配面。
        self.assertNotIn("@deepseek-ai/dsh-agent", manifest["peerDependencies"])

    def test_engines_use_a_range_not_a_pinned_runtime(self):
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertIn(">=", manifest["engines"]["dsh"])
        self.assertIn("<", manifest["engines"]["dsh"])

    def test_server_version_matches_the_package(self):
        import mcp_server
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(mcp_server.SERVER_VERSION, manifest["version"])

    def test_patch_inserts_the_plugin(self):
        content = read_text("cordis.patch.yml")
        self.assertIn("insert:", content)
        self.assertIn("dsh-zju-lecture-note", content)

    def test_skill_is_shipped(self):
        content = read_text("skills", "zju-lecture-summarizer", "SKILL.md")
        self.assertIn("公式书写规范", content)
        self.assertIn("zju_check_note", content)
        self.assertIn("不要在回复里回显登录 Cookie 明文", content)

    def test_bridge_points_at_the_python_core(self):
        content = read_text("lib", "bridge.js")
        self.assertIn('"mcp_server.py"', content)
        self.assertNotIn('join(PLUGIN_ROOT, "python"', content)

    def test_bridge_forces_utf8_for_the_python_child(self):
        content = read_text("lib", "bridge.js")
        self.assertIn("PYTHONUTF8", content)
        self.assertIn("PYTHONIOENCODING", content)


class TestDependencyDeclarations(unittest.TestCase):
    """lib/ 里出现的外部依赖必须在 package.json 里声明。

    包名拼错（把 ``@deepseek-ai/schemastery`` 写成 ``@deepseek-ai/schemamastery``）
    在 npm 上根本不存在：装不上、import 不到，用户看到的只有一句
    ``Cannot find package``。这类错误必须在上游就被钉住，而不是等用户踩。
    """

    def _declared(self):
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        return set(manifest.get("dependencies", {})) | set(manifest.get("peerDependencies", {}))

    def _imported(self):
        specifiers = set()
        lib_dir = os.path.join(ROOT, "lib")
        for name in sorted(os.listdir(lib_dir)):
            if not name.endswith(".js"):
                continue
            content = read_text("lib", name)
            specifiers.update(re.findall(r"""["'](@deepseek-ai/[^"']+)["']""", content))
        return specifiers

    def test_every_imported_package_is_declared(self):
        declared = self._declared()
        imported = self._imported()
        self.assertTrue(imported, "没扫到任何 @deepseek-ai 依赖，扫描规则可能已失效")
        for specifier in sorted(imported):
            self.assertIn(specifier, declared, f"lib/ 里引用的 {specifier} 未在 package.json 声明")

    def test_import_failure_tells_the_user_how_to_install(self):
        """缺依赖时要给出可执行的中文处置，而不是裸的 ERR_MODULE_NOT_FOUND。"""
        content = read_text("lib", "index.js")
        self.assertIn("importDependency", content)
        self.assertIn("缺少依赖", content)
        self.assertIn("dsh plugin --profile desktop add github:", content)

        result = run_node("--input-type=module", "-e", "await import('./lib/index.js')")
        if result.returncode == 0:
            self.skipTest("本机已装好依赖，复现不出缺依赖场景")
        combined = result.stdout + result.stderr
        self.assertIn("缺少依赖", combined)
        self.assertIn("dsh plugin --profile desktop add github:", combined)


class TestNoHomeDirectoryWrites(unittest.TestCase):
    """The plugin registers the bundled Skill in memory; it must not copy it
    into ``$DSH_HOME`` (or any other user directory)."""

    def test_entrypoint_uses_the_skill_registry(self):
        content = read_text("lib", "index.js")
        self.assertIn("ctx.skills.register", content)
        self.assertIn("registerSkill", content)

    def test_entrypoint_does_not_copy_files_into_the_home_directory(self):
        content = read_text("lib", "index.js")
        for forbidden in ("copyFile", "homedir", "readdir", "mkdir", "node:fs/promises"):
            self.assertNotIn(forbidden, content, f"lib/index.js 仍包含 {forbidden}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
