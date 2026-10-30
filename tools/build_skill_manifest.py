#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Skill 的文件清单（sha256 审计用）。

用法：
    python tools/build_skill_manifest.py
"""

import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILL_NAME = "zju-lecture-summarizer"
SKILL_DIR = os.path.join(ROOT, "skills", SKILL_NAME)
MANIFEST = os.path.join(ROOT, "skills", f"{SKILL_NAME}.manifest.json")
PACKAGE_JSON = os.path.join(ROOT, "package.json")

EXCLUDED_DIRS = {".git", "__pycache__", "node_modules"}
EXCLUDED_FILES = {".DS_Store", "README.en.md"}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect():
    files = []
    for root, dirs, names in os.walk(SKILL_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in sorted(names):
            if name in EXCLUDED_FILES or name.endswith(".pyc"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, SKILL_DIR).replace(os.sep, "/")
            files.append({
                "path": rel,
                "sha256": sha256(path),
                "size": os.path.getsize(path),
                "mode": "0644",
            })
    return sorted(files, key=lambda item: item["path"])


def package_version() -> str:
    """Keep the Skill manifest in step with the published plugin version."""
    with open(PACKAGE_JSON, encoding="utf-8") as handle:
        return str(json.load(handle).get("version") or "0.0.0")


def main() -> int:
    files = collect()
    manifest = {
        "name": SKILL_NAME,
        "version": package_version(),
        "fileCount": len(files),
        "files": files,
    }
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"已生成 Skill 清单: {len(files)} 个文件 -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
