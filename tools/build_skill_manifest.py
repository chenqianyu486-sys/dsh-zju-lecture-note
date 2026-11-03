#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成各 Skill 的文件清单（sha256 审计用）。

插件现在随包分发两个 Skill，清单脚本要能一次覆盖它们 —— 清单是
「装到用户机器上的那份」与「仓库里这份」是否一致的凭据，少一个就少一个
可核对的地方。

清单里有两个版本相关的字段：

* ``version`` —— 跟插件主版本一致（``package.json`` 的 version），
  插件升级时清单跟着升，Agent 才能从清单看出装的是哪一版；
* ``contentHash`` —— ``SKILL.md`` 本身的 sha256，用来发现「Skill 改了但
  清单没重新生成」这种漂移。

用法：
    python tools/build_skill_manifest.py
"""

import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: 随包分发的 Skill。清单里的版本号统一取插件主版本，不再各写各的。
SKILLS = (
    "zju-lecture-summarizer",
    "scholia-notes",
)

EXCLUDED_DIRS = {".git", "__pycache__", "node_modules"}
EXCLUDED_FILES = {".DS_Store", "README.en.md"}


def package_version():
    """The plugin's version — the one every shipped artifact agrees on."""
    with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
        return json.load(handle)["version"]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect(skill_name):
    skill_dir = os.path.join(ROOT, "skills", skill_name)
    files = []
    for root, dirs, names in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in sorted(names):
            if name in EXCLUDED_FILES or name.endswith(".pyc"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, skill_dir).replace(os.sep, "/")
            files.append({
                "path": rel,
                "sha256": sha256(path),
                "size": os.path.getsize(path),
                "mode": "0644",
            })
    return sorted(files, key=lambda item: item["path"])


def build(skill_name, version):
    files = collect(skill_name)
    skill_file = os.path.join(ROOT, "skills", skill_name, "SKILL.md")
    manifest = {
        "name": skill_name,
        "version": version,
        "contentHash": f"sha256:{sha256(skill_file)}",
        "fileCount": len(files),
        "files": files,
    }
    path = os.path.join(ROOT, "skills", f"{skill_name}.manifest.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path, len(files)


def main() -> int:
    version = package_version()
    for skill_name in SKILLS:
        path, count = build(skill_name, version)
        print(
            f"已生成 Skill 清单: {skill_name} v{version} {count} 个文件 "
            f"-> {os.path.relpath(path, ROOT)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
