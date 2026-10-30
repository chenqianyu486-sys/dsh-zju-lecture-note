#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build, validate and install the ZJU Lecture agent plugin package.

Usage:
    python tools/build_plugin.py --validate     # validate only
    python tools/build_plugin.py --install      # validate + install to the local plugin dir
    python tools/build_plugin.py --install --zip  # also produce dist/<name>-<version>.zip

The package layout follows the local MiniMax Plugin V1 specification:

    <plugin>/
      .minimax-plugin/plugin.json
      icon.png / icon-dark.png
      <name>.mcp.json
      server.mjs
      skills/<skill-name>/SKILL.md
      ...

Only the runtime files are copied into the installed package; the repository
keeps tests, adapters and tooling outside of it.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from typing import Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLUGIN_NAME = "zju-lecture"
CATEGORIES = {
    "Office", "Studio", "Design & Sites", "Code", "Business",
    "Sales", "Productivity", "Science & Healthcare", "Education", "Other",
}
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")
TRANSPORTS = {"stdio", "streamable-http", "sse"}

# Runtime files copied into the installed package (relative to the repo root).
PACKAGE_FILES = [
    ".minimax-plugin/plugin.json",
    "zju-lecture.mcp.json",
    "server.mjs",
    "mcp_server.py",
    "icon.png",
    "icon-dark.png",
    "LICENSE",
    "ATTRIBUTION.md",
    "README.md",
    "skills/zju-lecture-summarizer/SKILL.md",
]
PACKAGE_DIRS = ["zju_lecture"]

# V1 package limits.
MAX_ENTRIES = 2048
MAX_FILES = 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


class ValidationError(Exception):
    pass


def _read_json(path: str) -> dict:
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValidationError(f"{path} 含 BOM，必须使用无 BOM 的 UTF-8")
    text = raw.decode("utf-8")
    def _no_dupes(pairs):
        seen = {}
        for key, value in pairs:
            if key in seen:
                raise ValidationError(f"{path} 存在重复键: {key}")
            seen[key] = value
        return seen
    value = json.loads(text, object_pairs_hook=_no_dupes)
    if not isinstance(value, dict):
        raise ValidationError(f"{path} 根节点必须是对象")
    return value


def _check_relative_path(rel_path: str, where: str) -> None:
    if rel_path.startswith("/") or "\\" in rel_path or ":" in rel_path:
        raise ValidationError(f"{where} 必须使用相对路径与 '/' 分隔: {rel_path}")
    for segment in rel_path.split("/"):
        if not segment or segment in (".", ".."):
            raise ValidationError(f"{where} 含非法路径段: {rel_path}")
        if not SEGMENT_RE.match(segment):
            raise ValidationError(f"{where} 路径段只允许字母数字 . _ -: {rel_path}")
        if segment.endswith("."):
            raise ValidationError(f"{where} 路径段不能以 '.' 结尾: {rel_path}")


def validate_manifest(manifest: dict, manifest_path: str) -> List[str]:
    problems: List[str] = []
    for field in ("schemaVersion", "name", "version", "description", "author",
                  "icon", "category", "exampleQueries", "apps", "mcpServers", "skills"):
        if field not in manifest:
            problems.append(f"缺少必填字段: {field}")

    if manifest.get("schemaVersion") != 1:
        problems.append("schemaVersion 必须为 1")
    name = manifest.get("name", "")
    if name != PLUGIN_NAME:
        problems.append(f"name 必须为 {PLUGIN_NAME}，当前为 {name!r}")
    if not NAME_RE.match(name):
        problems.append(f"name 不符合命名规则: {name!r}")
    version = manifest.get("version", "")
    if not SEMVER_RE.match(version):
        problems.append(f"version 不是合法 SemVer: {version!r}")
    if manifest.get("category") not in CATEGORIES:
        problems.append(f"category 不在允许列表内: {manifest.get('category')!r}")
    if manifest.get("apps") != []:
        problems.append("apps 必须为 []")
    if not manifest.get("description", "").strip():
        problems.append("description 不能为空")
    if not isinstance(manifest.get("author"), (str, dict)) or not manifest.get("author"):
        problems.append("author 必须是非空字符串或对象")

    queries = manifest.get("exampleQueries")
    if not isinstance(queries, list) or not queries:
        problems.append("exampleQueries 必须是非空数组")
    else:
        for query in queries:
            if not isinstance(query, str) or not query.strip():
                problems.append("exampleQueries 每项都必须是非空字符串")

    for icon_field in ("icon", "darkIcon"):
        icon = manifest.get(icon_field)
        if not icon:
            continue
        _check_relative_path(icon, f"{icon_field}")
        icon_path = os.path.join(REPO_ROOT, icon)
        if not os.path.isfile(icon_path):
            problems.append(f"{icon_field} 指向的文件不存在: {icon}")
        elif not icon.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            problems.append(f"{icon_field} 必须是 PNG/JPEG/WebP: {icon}")

    for field in ("mcpServers", "skills", "agents", "hooks"):
        entries = manifest.get(field, [])
        if not isinstance(entries, list):
            problems.append(f"{field} 必须是数组")
            continue
        for entry in entries:
            _check_relative_path(entry, field)
            if not os.path.isfile(os.path.join(REPO_ROOT, entry)):
                problems.append(f"{field} 指向的文件不存在: {entry}")
            if field == "mcpServers" and not entry.endswith(".mcp.json"):
                problems.append(f"mcpServers 条目必须以 .mcp.json 结尾: {entry}")
            if field == "skills" and not re.match(r"^skills/[^/]+/SKILL\.md$", entry):
                problems.append(f"skills 条目必须形如 skills/<name>/SKILL.md: {entry}")

    return problems


def validate_mcp_file(mcp: dict, path: str) -> List[str]:
    problems: List[str] = []
    if mcp.get("schemaVersion") != 1:
        problems.append(f"{path}: schemaVersion 必须为 1")
    servers = mcp.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        problems.append(f"{path}: mcpServers 必须是非空对象")
        return problems
    for server_name, server in servers.items():
        if not NAME_RE.match(server_name):
            problems.append(f"{path}: 服务器名不符合命名规则: {server_name!r}")
        transport = server.get("type")
        if transport not in TRANSPORTS:
            problems.append(f"{path}: 不支持的传输类型 {transport!r}")
        if transport == "stdio":
            command = server.get("command", "")
            if not command or "/" in command or "\\" in command:
                problems.append(f"{path}: stdio command 必须是 PATH 可解析的无斜杠可执行名: {command!r}")
            for arg in server.get("args", []):
                if not isinstance(arg, str):
                    problems.append(f"{path}: args 必须是字符串数组")
                elif arg.startswith("/") or "\\" in arg:
                    problems.append(f"{path}: args 必须使用相对路径: {arg!r}")
        for forbidden in ("auth", "oauth", "refresh_token", "headers"):
            if forbidden in server:
                problems.append(f"{path}: 不支持字段 {forbidden}")
    return problems


def validate_skill(path: str) -> List[str]:
    problems: List[str] = []
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append(f"{path} 含 BOM")
    text = raw.decode("utf-8")
    if not text.startswith("---\n"):
        problems.append(f"{path} 缺少 YAML frontmatter")
        return problems
    end = text.find("\n---", 3)
    if end == -1:
        problems.append(f"{path} frontmatter 未闭合")
        return problems
    front = text[3:end]
    fields = {}
    for line in front.splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    expected = os.path.basename(os.path.dirname(path))
    if fields.get("name") != expected:
        problems.append(f"{path} frontmatter name 必须等于目录名 {expected!r}")
    if not fields.get("description", "").strip():
        problems.append(f"{path} frontmatter description 不能为空")
    return problems


def collect_package_files() -> List[str]:
    files = list(PACKAGE_FILES)
    for package_dir in PACKAGE_DIRS:
        abs_dir = os.path.join(REPO_ROOT, package_dir)
        if not os.path.isdir(abs_dir):
            continue
        for entry in sorted(os.listdir(abs_dir)):
            if entry.endswith(".py") and not entry.startswith("__"):
                files.append(f"{package_dir}/{entry}")
    return files


def validate_package() -> Tuple[List[str], dict]:
    problems: List[str] = []
    manifest_path = os.path.join(REPO_ROOT, ".minimax-plugin", "plugin.json")
    if not os.path.isfile(manifest_path):
        return [f"找不到清单: {manifest_path}"], {}

    manifest = _read_json(manifest_path)
    problems.extend(validate_manifest(manifest, manifest_path))

    # A root plugin.json would be picked up as an Agent Plugins V1 manifest and
    # would shadow the MiniMax manifest, so the package must not ship one.
    if os.path.isfile(os.path.join(REPO_ROOT, "plugin.json")):
        problems.append("包根存在 plugin.json：会遮蔽 .minimax-plugin 清单，请移出包外")

    for entry in manifest.get("mcpServers", []):
        mcp = _read_json(os.path.join(REPO_ROOT, entry))
        problems.extend(validate_mcp_file(mcp, entry))

    for entry in manifest.get("skills", []):
        problems.extend(validate_skill(os.path.join(REPO_ROOT, entry)))

    files = collect_package_files()
    total_bytes = 0
    for rel in files:
        abs_path = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(abs_path):
            problems.append(f"运行时文件缺失: {rel}")
            continue
        size = os.path.getsize(abs_path)
        total_bytes += size
        if size > MAX_FILE_BYTES:
            problems.append(f"文件超过 16MiB 限制: {rel}")
    if len(files) > MAX_FILES:
        problems.append(f"文件数超过 {MAX_FILES} 限制: {len(files)}")
    if total_bytes > MAX_TOTAL_BYTES:
        problems.append(f"总体积超过 64MiB 限制: {total_bytes}")

    return problems, manifest


def stage_package(staging: str) -> None:
    for rel in collect_package_files():
        src = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(staging, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def install_package(dest: str) -> None:
    parent = os.path.dirname(os.path.abspath(dest))
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix="zju-lecture-build-")
    try:
        stage_package(staging)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.move(staging, dest)
        staging = ""
    finally:
        if staging and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)


def make_zip(dest: str, version: str) -> str:
    dist_dir = os.path.join(REPO_ROOT, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    zip_path = os.path.join(dist_dir, f"{PLUGIN_NAME}-{version}.zip")
    staging = tempfile.mkdtemp(prefix="zju-lecture-zip-")
    try:
        stage_package(staging)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for root, _dirs, names in os.walk(staging):
                for name in sorted(names):
                    abs_path = os.path.join(root, name)
                    arcname = os.path.join(
                        PLUGIN_NAME, os.path.relpath(abs_path, staging).replace(os.sep, "/")
                    )
                    archive.write(abs_path, arcname)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 / 打包 / 安装 ZJU Lecture 插件")
    parser.add_argument("--validate", action="store_true", help="只做校验")
    parser.add_argument("--install", action="store_true", help="安装到本地插件目录")
    parser.add_argument("--zip", action="store_true", help="生成 dist/<name>-<version>.zip")
    parser.add_argument(
        "--dest",
        default=os.path.join(os.environ.get("MINIMAX_DATA_DIR", "C:/Users/me/.minimax"), "plugins", PLUGIN_NAME),
        help="安装目标目录",
    )
    args = parser.parse_args()

    problems, manifest = validate_package()
    if problems:
        print("校验未通过：")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    version = manifest.get("version", "0.0.0")
    print(f"校验通过：{manifest.get('name')} v{version}（{len(collect_package_files())} 个运行时文件）")

    if args.zip:
        zip_path = make_zip(args.dest, version)
        print(f"已打包: {zip_path}")

    if args.install:
        install_package(args.dest)
        print(f"已安装: {os.path.abspath(args.dest)}")

    if not (args.zip or args.install or args.validate):
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
