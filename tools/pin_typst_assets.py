#!/usr/bin/env python3
"""生成 ``zju_lecture/typst_assets.json``：各平台 Typst 资产的固定 SHA256。

Typst 的 GitHub Release 不提供 ``.sha256`` 文件，所以自动下载必须先由维护者
下载一次、把校验和钉进仓库；运行时只信任清单里的哈希，不接受「下载后看
``--version`` 对不对」这种弱校验。

用法::

    python tools/pin_typst_assets.py --version 0.15.1
    python tools/pin_typst_assets.py --version 0.15.1 --only win32-x86_64
    python tools/pin_typst_assets.py --check          # 只校验现有清单

产物格式::

    {
      "version": "0.15.1",
      "generated_at": "2026-11-03",
      "min_version": "0.13.0",
      "assets": {
        "win32-x86_64": {"file": "typst-x86_64-pc-windows-msvc.zip",
                          "sha256": "...", "size": 22463684, "kind": "zip"},
        ...
      }
    }
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MANIFEST = os.path.join(ROOT, "zju_lecture", "typst_assets.json")
RELEASE = "https://github.com/typst/typst/releases/download/v{version}/{file}"

# 平台键 → (release 资产名, 归档类型)
ASSETS = {
    "win32-x86_64": ("typst-x86_64-pc-windows-msvc.zip", "zip"),
    "win32-arm64": ("typst-aarch64-pc-windows-msvc.zip", "zip"),
    "darwin-x86_64": ("typst-x86_64-apple-darwin.tar.xz", "tar.xz"),
    "darwin-arm64": ("typst-aarch64-apple-darwin.tar.xz", "tar.xz"),
    "linux-x86_64": ("typst-x86_64-unknown-linux-musl.tar.xz", "tar.xz"),
    "linux-arm64": ("typst-aarch64-unknown-linux-musl.tar.xz", "tar.xz"),
}


def _ssl_context() -> ssl.SSLContext:
    """复用插件自带的 CA bundle（dsh 的 Python 没有 certifi）。"""
    try:
        from zju_lecture.client import get_ssl_context

        return get_ssl_context()
    except Exception:  # noqa: BLE001 - 构建脚本不该因为导入失败而停住
        return ssl.create_default_context()


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: str, retries: int = 3) -> None:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "zju-lecture-plugin/pin-assets"}
            )
            with urllib.request.urlopen(request, timeout=180, context=_ssl_context()) as response:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                with open(target, "wb") as handle:
                    while True:
                        chunk = response.read(1 << 20)
                        if not chunk:
                            break
                        handle.write(chunk)
                        done += len(chunk)
                        if total and done % (5 << 20) < (1 << 20):
                            print(f"\r  {done * 100 // total:3d}%  {done/1e6:5.1f}/{total/1e6:.1f} MB", end="")
                print()
                return
        except Exception as exc:  # noqa: BLE001 - 网络抖动要重试
            last = exc
            print(f"\n  第 {attempt} 次下载失败：{exc}")
            if attempt < retries:
                time.sleep(2 * attempt)
    raise SystemExit(f"下载失败（已重试 {retries} 次）：{url}\n{last}")


def load_manifest() -> dict:
    if not os.path.isfile(MANIFEST):
        return {}
    with open(MANIFEST, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_manifest(data: dict) -> None:
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def check() -> int:
    data = load_manifest()
    if not data:
        print(f"清单不存在：{MANIFEST}")
        return 1
    bad = 0
    for platform, entry in sorted(data.get("assets", {}).items()):
        size = entry.get("size")
        sha = entry.get("sha256", "")
        if not sha or len(sha) != 64 or not isinstance(size, int) or size <= 0:
            print(f"✗ {platform}: 字段不完整")
            bad += 1
        else:
            print(f"✓ {platform}: {entry['file']}  {size/1e6:.1f} MB  {sha[:16]}…")
    print(f"\n版本 {data.get('version')}，最小版本 {data.get('min_version')}，"
          f"{len(data.get('assets', {}))} 个平台，{bad} 个问题")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.15.1")
    parser.add_argument("--only", action="append", default=[],
                        help="只处理指定平台（可重复），例如 win32-x86_64")
    parser.add_argument("--check", action="store_true", help="只校验现有清单")
    parser.add_argument("--keep-dir", default=os.path.join(ROOT, ".cache", "typst-assets"),
                        help="归档缓存目录（中断后重跑可复用）")
    args = parser.parse_args()

    if args.check:
        return check()

    wanted = args.only or list(ASSETS)
    unknown = [key for key in wanted if key not in ASSETS]
    if unknown:
        print(f"未知平台：{', '.join(unknown)}；可选：{', '.join(ASSETS)}")
        return 2

    data = load_manifest()
    data["version"] = args.version
    data["min_version"] = data.get("min_version", "0.13.0")
    data["generated_at"] = datetime.date.today().isoformat()
    assets = data.setdefault("assets", {})

    keep = os.path.abspath(args.keep_dir)
    os.makedirs(keep, exist_ok=True)

    for platform in wanted:
        file_name, kind = ASSETS[platform]
        url = RELEASE.format(version=args.version, file=file_name)
        print(f"\n{platform}: {url}")
        target = os.path.join(keep, file_name)
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            print(f"  复用已下载文件：{target}")
        else:
            download(url, target)
            # 每下完一个就落盘一次：中断后重跑可以复用已完成的归档。
        size = os.path.getsize(target)
        digest = sha256_of(target)
        assets[platform] = {
            "file": file_name,
            "sha256": digest,
            "size": size,
            "kind": kind,
        }
        save_manifest(data)
        print(f"  ✓ {size/1e6:.1f} MB  {digest}")

    print(f"\n写入 {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
