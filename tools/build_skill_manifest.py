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
    # A SKILL.md front matter carries only name/description — there is no
    # version field to compare, so an installed copy can silently drift from
    # the plugin (and an old copy can still advise users to hand over a
    # cookie). The content hash is the only reliable drift signal, so publish
    # it explicitly instead of burying it in files[].sha256.
    skill_hash = next((item["sha256"] for item in files if item["path"] == "SKILL.md"), "")
    manifest = {
        "name": SKILL_NAME,
        "version": package_version(),
        "contentHash": f"sha256:{skill_hash}",
        "fileCount": len(files),
        "files": files,
    }
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"已生成 Skill 清单: {len(files)} 个文件 -> {MANIFEST}")
    print(f"SKILL.md contentHash: sha256:{skill_hash[:12]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
