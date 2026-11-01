#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷新随包的 CA 证书库 ``zju_lecture/cacert.pem``。

用法：
    python tools/refresh_ca_bundle.py              # 优先取本机 certifi
    python tools/refresh_ca_bundle.py --download   # 从 curl.se 取最新 Mozilla 快照
    python tools/refresh_ca_bundle.py --check      # 只报告当前是否过期

为什么需要这份文件：dsh 自带的 Python 解释器不含 certifi，而
``ssl.create_default_context()`` 在根证书不全的机器上会直接
``CERTIFICATE_VERIFY_FAILED``。随包一份 Mozilla 根证书快照，让"能不能抓字幕"
不再取决于用户碰巧 pip 装了什么。

许可：certifi 的 ``cacert.pem`` 源自 Mozilla CA Certificate Program，按 MPL-2.0 分发；
详见 ``ATTRIBUTION.md``。
"""

import argparse
import hashlib
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TARGET = os.path.join(ROOT, "zju_lecture", "cacert.pem")

DOWNLOAD_URL = "https://curl.se/ca/cacert.pem"
MAX_BYTES = 4 * 1024 * 1024
# 低于这个数量的根证书基本可以判定是残缺文件
MIN_CERTS = 50

HEADER = """# Bundled CA certificate store for dsh-zju-lecture-note / zju-lecture-mcp.
#
# Origin : certifi's cacert.pem (https://github.com/certifi/python-certifi),
#          derived from the Mozilla CA Certificate Program root store.
# License: Mozilla Public License 2.0, as distributed by certifi.
# Snapshot sha256 (upstream file): {sha256}
# Refreshed by: python tools/refresh_ca_bundle.py
#
# Why this file exists: dsh ships its own Python interpreter without certifi, and a
# plain `ssl.create_default_context()` on an incomplete OS root store yields
# CERTIFICATE_VERIFY_FAILED. This bundle is the fallback between certifi and the OS
# store. It is refreshed by `python tools/refresh_ca_bundle.py`.
#
# Do not edit by hand.
"""


def certifi_bundle() -> bytes:
    import certifi  # 延迟导入：没有 certifi 时走 --download

    with open(certifi.where(), "rb") as handle:
        return handle.read()


def download_bundle() -> bytes:
    with urllib.request.urlopen(DOWNLOAD_URL, timeout=60) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise RuntimeError("下载内容异常大，拒绝写入")
    return data


def count_certs(data: bytes) -> int:
    return data.count(b"-----BEGIN CERTIFICATE-----")


def main() -> int:
    parser = argparse.ArgumentParser(description="刷新随包 CA 证书库")
    parser.add_argument("--download", action="store_true", help="改用 curl.se 的 Mozilla 快照")
    parser.add_argument("--check", action="store_true", help="只检查现有文件是否可用")
    args = parser.parse_args()

    if args.check:
        if not os.path.isfile(TARGET):
            print(f"缺少 {TARGET}")
            return 1
        with open(TARGET, "rb") as handle:
            data = handle.read()
        total = count_certs(data)
        print(f"{TARGET}: {len(data)} 字节 / {total} 张证书")
        return 0 if total >= MIN_CERTS else 1

    data = download_bundle() if args.download else certifi_bundle()
    total = count_certs(data)
    if total < MIN_CERTS:
        print(f"拒绝写入：只解析出 {total} 张证书（下限 {MIN_CERTS}）", file=sys.stderr)
        return 1

    sha = hashlib.sha256(data).hexdigest()
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with open(TARGET, "wb") as handle:
        handle.write(HEADER.format(sha256=sha).encode("utf-8") + data)

    print(f"已写入 {TARGET}")
    print(f"  {total} 张证书 / {os.path.getsize(TARGET)} 字节 / upstream sha256={sha}")
    print("  记得更新 ATTRIBUTION.md 里的快照哈希与同步日期。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
