#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent Plugins 1.0 通用入口的合规回归。

仓库根同时是 dsh 原生 npm 包与 Agent Plugins 1.0 包。这组测试守的是后者：
两份根清单符合官方 schema（``additionalProperties: false``，所以多一个键就非法）、
``skills/`` 能按标准被发现、npm 产物带上入口所需的三个文件，以及旧打包脚本的产物
不会把根清单混进去。全部用 stdlib 离线断言，不依赖网络与 ``jsonschema``。
"""

import importlib.util
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

#: plugin.schema.json 的全部合法顶层键（required: $schema / name）。
PLUGIN_KEYS = {
    "$schema", "name", "version", "description", "author",
    "homepage", "repository", "license", "keywords", "extensions",
}
PLUGIN_NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: mcp.schema.json 的 stdioServer 合法键（required: type / command）。
STDIO_KEYS = {"type", "command", "args", "env", "cwd"}

SKILL_DIRS = (
    "zju-lecture-summarizer",
    "zju-lecture-summarizer-help",
    "zju-lecture-summarizer-login",
    "scholia-notes",
)


def read_text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def load_strict_json(*parts):
    """无 BOM、无重复键的 UTF-8 JSON——规范对清单文件的硬要求。"""
    path = os.path.join(ROOT, *parts)
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise AssertionError(f"{path} 含 BOM")

    def no_dupes(pairs):
        seen = set()
        for key, _value in pairs:
            if key in seen:
                raise AssertionError(f"{path} 存在重复键: {key}")
            seen.add(key)
        return dict(pairs)

    return json.loads(raw.decode("utf-8"), object_pairs_hook=no_dupes)


def frontmatter(path):
    """取 SKILL.md 的顶层 frontmatter 标量值，支持 ``|`` / ``>`` 块标量。"""
    lines = read_text(*path).splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        close = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}
    fields = {}
    key = None
    block = []
    for line in lines[1:close]:
        matched = re.match(r"^([A-Za-z0-9_-]+):(.*)$", line)
        if matched:
            if key is not None:
                fields[key] = "\n".join(block).strip() if block else fields[key]
            key = matched.group(1)
            value = matched.group(2).strip()
            block = []
            fields[key] = "" if value in ("|", ">", "|-", ">-") else value.strip('"')
        elif key is not None and line.startswith((" ", "\t")):
            block.append(line.strip())
    if key is not None and block:
        fields[key] = "\n".join(block).strip()
    return fields


def load_build_plugin():
    spec = importlib.util.spec_from_file_location(
        "build_plugin", os.path.join(ROOT, "tools", "build_plugin.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPluginManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = load_strict_json("plugin.json")

    def test_required_keys_and_no_extras(self):
        self.assertIn("$schema", self.manifest)
        self.assertIn("name", self.manifest)
        self.assertEqual(self.manifest["$schema"], PLUGIN_SCHEMA)
        # additionalProperties: false —— icon / category / skills / mcpServers 之类都不合法。
        self.assertLessEqual(set(self.manifest), PLUGIN_KEYS)

    def test_name_is_valid(self):
        name = self.manifest["name"]
        self.assertIsInstance(name, str)
        self.assertTrue(1 <= len(name) <= 64, name)
        self.assertRegex(name, PLUGIN_NAME_RE)

    def test_author_is_an_object(self):
        author = self.manifest.get("author")
        if author is not None:
            self.assertIsInstance(author, dict)
            self.assertLessEqual(set(author), {"name", "email", "url"})
            self.assertTrue(all(isinstance(v, str) for v in author.values()))

    def test_optional_field_types(self):
        for field in ("version", "description", "homepage", "repository", "license"):
            if field in self.manifest:
                self.assertIsInstance(self.manifest[field], str, field)
        keywords = self.manifest.get("keywords", [])
        self.assertIsInstance(keywords, list)
        self.assertTrue(all(isinstance(k, str) for k in keywords))

    def test_version_matches_the_npm_package(self):
        self.assertEqual(
            self.manifest["version"], load_strict_json("package.json")["version"]
        )


class TestMcpManifest(unittest.TestCase):
    def setUp(self):
        self.config = load_strict_json("mcp.json")
        self.server = self.config["mcpServers"]["zju-lecture"]

    def test_root_shape(self):
        self.assertEqual(set(self.config), {"$schema", "mcpServers"})
        self.assertEqual(self.config["$schema"], MCP_SCHEMA)
        self.assertIsInstance(self.config["mcpServers"], dict)
        self.assertTrue(self.config["mcpServers"])

    def test_stdio_server_shape(self):
        self.assertLessEqual(set(self.server), STDIO_KEYS)
        self.assertEqual(self.server["type"], "stdio")
        self.assertEqual(self.server["command"], "node")
        self.assertEqual(self.server["args"], ["./server.mjs"])
        # 省略 cwd：规范要求客户端以插件根为工作目录，而部分客户端不展开
        # ${PLUGIN_ROOT} / ${PLUGIN_DATA}，写死占位符反而不跨客户端。
        self.assertNotIn("cwd", self.server)

    def test_no_legacy_extra_fields(self):
        # 这三项在旧 zju-lecture.mcp.json 里合法，在 Agent Plugins schema 里非法。
        for field in ("description", "timeout", "schemaVersion"):
            self.assertNotIn(field, self.server)
            self.assertNotIn(field, self.config)

    def test_env_is_string_map_without_reserved_keys(self):
        env = self.server.get("env", {})
        self.assertIsInstance(env, dict)
        self.assertTrue(all(isinstance(v, str) for v in env.values()))
        self.assertNotIn("PLUGIN_ROOT", env)
        self.assertNotIn("PLUGIN_DATA", env)

    def test_env_matches_the_legacy_mcp_entry(self):
        legacy = load_strict_json("zju-lecture.mcp.json")["mcpServers"]["zju-lecture"]
        self.assertEqual(self.server["env"], legacy["env"])

    def test_launcher_resolves_against_the_plugin_root(self):
        rel = self.server["args"][0]
        self.assertTrue(rel.startswith("./"))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, rel[2:])))


class TestSkillDiscovery(unittest.TestCase):
    def test_exactly_the_four_skill_dirs_are_discovered(self):
        # 标准只看 skills/ 的直接子目录里有没有 SKILL.md；sibling 的 *.manifest.json 不算。
        found = sorted(
            name
            for name in os.listdir(os.path.join(ROOT, "skills"))
            if os.path.isfile(os.path.join(ROOT, "skills", name, "SKILL.md"))
        )
        self.assertEqual(found, sorted(SKILL_DIRS))

    def test_frontmatter_names_match_their_directory(self):
        for name in SKILL_DIRS:
            fields = frontmatter(("skills", name, "SKILL.md"))
            self.assertEqual(fields.get("name"), name)
            self.assertTrue(1 <= len(name) <= 64, name)
            self.assertRegex(name, SKILL_NAME_RE)

    def test_descriptions_are_within_the_agent_skills_limit(self):
        for name in SKILL_DIRS:
            description = frontmatter(("skills", name, "SKILL.md")).get("description", "")
            self.assertTrue(1 <= len(description) <= 1024, f"{name}: {len(description)}")


class TestNpmPackageShipsTheEntry(unittest.TestCase):
    def test_files_include_the_three_entry_files(self):
        files = load_strict_json("package.json")["files"]
        for entry in ("plugin.json", "mcp.json", "server.mjs"):
            self.assertIn(entry, files)

    def test_dsh_metadata_is_untouched(self):
        package = load_strict_json("package.json")
        self.assertEqual(package["name"], "dsh-zju-lecture-note")
        self.assertEqual(package["main"], "./lib/index.js")
        self.assertEqual(package["dsh"]["manifestVersion"], 1)
        self.assertEqual(package["dsh"]["bundle"]["patch"], "./cordis.patch.yml")


class TestLegacyPackageIsolation(unittest.TestCase):
    def test_root_manifests_are_not_collected(self):
        collected = load_build_plugin().collect_package_files()
        self.assertNotIn("plugin.json", collected)
        self.assertNotIn("mcp.json", collected)

    def test_validate_passes_with_root_manifests_present(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "plugin.json")))
        problems, _manifest = load_build_plugin().validate_package()
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()