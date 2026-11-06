"""Typst 依赖自举：查找 → 版本校验 → 按平台下载 → SHA256 校验 → 缓存。

设计目标：**即开即用**。用户装完插件第一次写讲义时，不应该需要自己去装
Typst。这里把「没有 Typst」从一个静默失败（`PDF 跳过`）变成一次可解释的
自举：

1. 先按 `ZJU_TYPST_BIN` → 插件缓存 → PATH → 常见安装目录的次序查找；
2. 找到但版本 < 0.13.0 时提示升级（0.13 是 `--package-path` 与现有模板的下限）；
3. 找不到且允许自动安装时，从 GitHub Release 下载对应平台的归档，
   **只信任** ``zju_lecture/typst_assets.json`` 里钉死的 SHA256；
4. 解压到用户缓存目录，校验 ``typst --version`` 与清单一致后启用。

供应链边界
----------
- 只从 ``https://github.com/typst/typst/releases`` 下载；可用
  ``ZJU_TYPST_MIRROR`` 加前缀走镜像（例如 ``https://ghfast.top/``），
  但镜像只影响传输路径，哈希仍按清单校验。
- 下载与执行第三方二进制是敏感操作：``ZJU_TYPST_AUTO_INSTALL=0`` 可关闭，
  关闭后只返回安装建议，不联网、不写盘。
- 本模块不读取、不传输任何登录态；与 Cookie / 课堂会话完全无关。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .security import REDACTOR

TYPST_ENV = "ZJU_TYPST_BIN"
AUTO_INSTALL_ENV = "ZJU_TYPST_AUTO_INSTALL"
MIRROR_ENV = "ZJU_TYPST_MIRROR"
ASSETS_ENV = "ZJU_TYPST_ASSETS"
MIN_VERSION = (0, 13, 0)

RELEASE_URL = "https://github.com/typst/typst/releases/download/v{version}/{file}"
CACHE_APP = "dsh-zju-lecture"

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(HERE, "typst_assets.json")
PACKAGE_PATH = os.path.join(HERE, "typst-packages")
FONT_PATH = os.path.join(HERE, "fonts")


@dataclass
class TypstInfo:
    """One probe result. ``errors`` is for the doctor/UI, never raised."""

    path: Optional[str] = None
    version: Optional[Tuple[int, int, int]] = None
    source: str = "missing"          # env / cache / path / system / missing
    ok: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def version_text(self) -> str:
        if not self.version:
            return "未知"
        return ".".join(str(part) for part in self.version)


# ---------------------------------------------------------------- 路径


def auto_install_enabled() -> bool:
    """自动下载开关：默认开启，``ZJU_TYPST_AUTO_INSTALL=0`` 关闭。"""
    raw = os.environ.get(AUTO_INSTALL_ENV, "").strip().lower()
    return raw not in ("0", "false", "no", "off")


CACHE_ENV = "ZJU_TYPST_CACHE"


def cache_root() -> str:
    """用户级缓存目录（不写工作区，避免每节课都重下 20MB）。

    ``ZJU_TYPST_CACHE`` 可整体覆盖：便于测试与把缓存放到别的盘。
    """
    override = os.environ.get(CACHE_ENV, "").strip()
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
        return os.path.join(base, CACHE_APP, "typst")
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Caches/{CACHE_APP}/typst")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, CACHE_APP, "typst")


def cached_binary(version: str) -> str:
    name = "typst.exe" if sys.platform == "win32" else "typst"
    return os.path.join(cache_root(), f"v{version}", name)


def package_path() -> str:
    """随包分发的 ``@preview`` 包目录（``--package-path``）。不存在返回空串。"""
    return PACKAGE_PATH if os.path.isdir(PACKAGE_PATH) else ""


def font_path() -> str:
    """随包分发的中文子集字体目录（``--font-path``）。不存在返回空串。"""
    return FONT_PATH if os.path.isdir(FONT_PATH) else ""


def compile_cache_path(workspace_root: str) -> str:
    """Typst 的包缓存目录：放进工作区，避免污染用户目录，也便于清理。"""
    root = os.path.abspath(workspace_root or os.getcwd())
    return os.path.join(root, ".zju-lecture", "typst-cache")


# ---------------------------------------------------------------- 清单


def load_manifest() -> Dict[str, Any]:
    path = os.environ.get(ASSETS_ENV, "").strip() or MANIFEST_PATH
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def manifest_version() -> str:
    return str(load_manifest().get("version") or "")


def platform_key() -> Optional[str]:
    """把当前解释器映射到清单里的平台键；不支持时返回 ``None``。"""
    system = sys.platform
    machine = (platform.machine() or "").lower()
    if machine in ("amd64", "x86_64", "x64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        return None

    if system == "win32":
        return f"win32-{arch}" if arch in ("x86_64", "arm64") else None
    if system == "darwin":
        return f"darwin-{arch}"
    if system.startswith("linux"):
        return f"linux-{arch}"
    return None


# ---------------------------------------------------------------- 查找


def _candidate_paths() -> List[str]:
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".cargo", "bin", "typst"),
        os.path.join(home, ".local", "bin", "typst"),
        os.path.join(home, "AppData", "Local", "Programs", "typst", "typst.exe"),
        "/usr/local/bin/typst",
        "/opt/homebrew/bin/typst",
        "/usr/bin/typst",
    ]
    if sys.platform == "win32":
        candidates.append(os.path.join(home, ".cargo", "bin", "typst.exe"))
        candidates.append(os.path.join(home, ".local", "bin", "typst.exe"))
    return candidates


def find_typst() -> Optional[str]:
    """按「显式指定 → 插件缓存 → PATH → 常见目录」找可执行文件。

    找不到返回 ``None``；这里**不**联网、不安装。
    """
    override = os.environ.get(TYPST_ENV, "").strip()
    if override:
        if os.path.isfile(override):
            return override
        found = shutil.which(override)
        if found:
            return found

    version = manifest_version()
    if version:
        cached = cached_binary(version)
        if os.path.isfile(cached):
            return cached

    found = shutil.which("typst")
    if found:
        return found

    for candidate in _candidate_paths():
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def typst_version(path: str) -> Optional[Tuple[int, int, int]]:
    """解析 ``typst --version`` → ``(major, minor, patch)``，失败返回 ``None``。"""
    try:
        completed = subprocess.run(
            [path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = completed.stdout.decode("utf-8", errors="replace")
    for token in text.replace("\n", " ").split():
        parts = token.split(".")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            return (int(parts[0]), int(parts[1]), int(parts[2]))
    return None


def _source_of(path: str) -> str:
    override = os.environ.get(TYPST_ENV, "").strip()
    if override and (os.path.abspath(path) == os.path.abspath(override) or path == override):
        return "env"
    version = manifest_version()
    if version and os.path.abspath(path) == os.path.abspath(cached_binary(version)):
        return "cache"
    return "path"


def probe(auto_install: bool = False) -> TypstInfo:
    """查找 + 版本校验；``auto_install`` 为真时缺失可触发一次自举。"""
    path = find_typst()
    if path:
        version = typst_version(path)
        info = TypstInfo(path=path, version=version, source=_source_of(path))
        if version and version >= MIN_VERSION:
            info.ok = True
            return info
        info.notes.append(
            f"找到 Typst {info.version_text}，但需要 ≥ {'.'.join(map(str, MIN_VERSION))}。"
        )
        if not auto_install:
            return info
        with_install = install(force=True)
        if with_install.path:
            return with_install
        info.notes.extend(with_install.notes)
        return info

    if not auto_install:
        return TypstInfo(notes=["未找到 Typst；可用 zju_doctor(install=true) 或手动安装。"])

    return install()


# ---------------------------------------------------------------- 安装


_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def _redact_url(url: str) -> str:
    """只保留 ``scheme://host[:port]/path``，去掉 userinfo / query / fragment。"""
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlparse(text)
    except ValueError:
        return "[REDACTED]"
    if not parsed.scheme or not parsed.netloc:
        return REDACTOR.redact(text)
    host = parsed.hostname or ""
    netloc = f"[{host}]" if ":" in host and not host.startswith("[") else host
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port:
        netloc = f"{netloc}:{port}"
    return REDACTOR.redact(f"{parsed.scheme}://{netloc}{parsed.path}")


def _redact_text(message: object) -> str:
    """脱敏任意诊断文本：先洗掉 URL 里的凭据，再交给进程级 redactor。"""
    text = str(message)
    text = _URL_RE.sub(lambda match: _redact_url(match.group(0)), text)
    return REDACTOR.redact(text)


def _progress(message: str) -> None:
    """进度只写 stderr：工具的返回值要保持可读，不混入下载日志。

    镜像 URL 可能带 userinfo 或签名 query；进入 stderr 前必须先脱敏，
    否则宿主的日志/会话记录会替用户保存一份凭据。
    """
    try:
        sys.stderr.write(_redact_text(message) + "\n")
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 - 日志永远不能影响主流程
        pass


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: str, retries: int = 3) -> None:
    import urllib.request

    try:
        from .client import get_ssl_context

        context = get_ssl_context()
    except Exception:  # noqa: BLE001 - 兜底系统证书
        import ssl

        context = ssl.create_default_context()

    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "zju-lecture-plugin/typst"}
            )
            with urllib.request.urlopen(request, timeout=180, context=context) as response:
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
                            _progress(
                                f"  下载 Typst {done * 100 // max(total, 1)}% "
                                f"({done/1e6:.0f}/{total/1e6:.0f} MB)"
                            )
                return
        except Exception as exc:  # noqa: BLE001 - 网络抖动要重试
            last = exc
            _progress(f"  下载失败（第 {attempt}/{retries} 次）：{exc}")
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(_redact_text(last) if last else "下载失败")


def _safe_members(archive: zipfile.ZipFile | tarfile.TarFile) -> List[str]:
    """拒绝绝对路径与 ``..``：解压不能让归档写到缓存目录之外。"""
    names: List[str] = []
    if isinstance(archive, zipfile.ZipFile):
        for name in archive.namelist():
            normalized = os.path.normpath(name)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise ValueError(f"归档包含可疑路径：{name}")
            names.append(name)
    else:
        for member in archive.getmembers():
            normalized = os.path.normpath(member.name)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise ValueError(f"归档包含可疑路径：{member.name}")
            names.append(member.name)
    return names


def _extract(archive_path: str, kind: str, destination: str) -> str:
    """解压归档并返回 ``typst`` 可执行文件的路径。"""
    os.makedirs(destination, exist_ok=True)
    binary_name = "typst.exe" if sys.platform == "win32" else "typst"

    if kind == "zip":
        with zipfile.ZipFile(archive_path) as archive:
            _safe_members(archive)
            archive.extractall(destination)
    else:
        with tarfile.open(archive_path, "r:xz") as archive:
            _safe_members(archive)
            archive.extractall(destination)

    for current, _dirs, files in os.walk(destination):
        if binary_name in files:
            return os.path.join(current, binary_name)
    raise ValueError("归档里找不到 typst 可执行文件")


FAILURE_COOLDOWN_SECONDS = 6 * 3600


def _failure_marker() -> str:
    return os.path.join(cache_root(), ".install-failed")


def _failure_recent() -> bool:
    """下载失败后 6 小时内不再自动重试：避免每写一份讲义都卡一次超时。"""
    try:
        age = time.time() - os.path.getmtime(_failure_marker())
    except OSError:
        return False
    return age < FAILURE_COOLDOWN_SECONDS


def _mark_failure() -> None:
    try:
        marker = _failure_marker()
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write(str(int(time.time())))
    except OSError:
        pass


def _clear_failure() -> None:
    try:
        os.remove(_failure_marker())
    except OSError:
        pass


def _mirror_url(url: str) -> str:
    prefix = os.environ.get(MIRROR_ENV, "").strip()
    if not prefix:
        return url
    return prefix.rstrip("/") + "/" + url


def _fail(notes: List[str]) -> TypstInfo:
    _mark_failure()
    return TypstInfo(notes=notes)


def install(force: bool = False) -> TypstInfo:
    """下载并安装清单里钉死版本的 Typst；失败时返回带说明的 ``TypstInfo``。"""
    manifest = load_manifest()
    version = str(manifest.get("version") or "")
    if not version:
        return TypstInfo(notes=[f"缺少 Typst 资产清单：{MANIFEST_PATH}"])

    target = cached_binary(version)
    if os.path.isfile(target) and not force:
        info = probe(auto_install=False)
        if info.ok:
            return info

    if not force and _failure_recent():
        return TypstInfo(notes=[
            "上次自动安装 Typst 失败，6 小时内不再自动重试；"
            "运行 zju_doctor(install=true) 立即重试，或手动安装后设置 ZJU_TYPST_BIN。",
        ])

    key = platform_key()
    assets = manifest.get("assets") or {}
    if not key or key not in assets:
        return _fail([
            f"当前平台（{sys.platform}/{platform.machine()}）没有预置的 Typst 资产；"
            "请手动安装 Typst ≥ 0.13 并设置 ZJU_TYPST_BIN。",
        ])

    entry = assets[key]
    url = _mirror_url(RELEASE_URL.format(version=version, file=entry["file"]))
    os.makedirs(os.path.dirname(target), exist_ok=True)

    with tempfile.TemporaryDirectory(dir=os.path.dirname(target), prefix=".download-") as tmp:
        archive_path = os.path.join(tmp, entry["file"])
        try:
            _progress(f"首次排版需要 Typst v{version}（{entry['size']/1e6:.0f} MB，Apache-2.0）：{url}")
            _download(url, archive_path)
        except Exception as exc:  # noqa: BLE001 - 网络失败要能解释
            return _fail([
                f"下载 Typst 失败：{_redact_text(exc)}",
                "可设置 ZJU_TYPST_MIRROR 走镜像，或手动安装后设置 ZJU_TYPST_BIN。",
            ])

        digest = _sha256(archive_path)
        if digest != entry["sha256"]:
            return _fail([
                "Typst 归档 SHA256 与清单不符，已拒绝安装。",
                f"期望 {entry['sha256']}，实际 {digest}。",
                "若上游重新打包，需要维护者重新运行 tools/pin_typst_assets.py。",
            ])

        unpacked = os.path.join(tmp, "unpacked")
        try:
            binary = _extract(archive_path, entry.get("kind", "zip"), unpacked)
        except Exception as exc:  # noqa: BLE001
            return _fail([f"解压 Typst 失败：{exc}"])

        if sys.platform != "win32":
            try:
                os.chmod(binary, 0o755)
            except OSError:
                pass
        shutil.copyfile(binary, target)
        if sys.platform != "win32":
            try:
                os.chmod(target, 0o755)
            except OSError:
                pass

    installed = typst_version(target)
    expected = tuple(int(part) for part in version.split(".")[:3])
    if installed != expected:
        try:
            os.remove(target)
        except OSError:
            pass
        return _fail([
            f"安装后版本校验失败：期望 {version}，得到 {installed}；已删除不可信文件。",
        ])

    _clear_failure()
    _progress(f"Typst v{version} 已就绪：{target}")
    return TypstInfo(path=target, version=installed, source="cache", ok=True)


# ---------------------------------------------------------------- 诊断


def describe(workspace_root: str = "", auto_install: bool = False) -> Dict[str, Any]:
    """给 ``zju_doctor`` 用的快照：不抛异常，缺什么就写什么。"""
    info = probe(auto_install=auto_install)
    manifest = load_manifest()
    return {
        "version": sys.version.split()[0],
        "platform": f"{sys.platform}/{platform.machine()}",
        "typst_path": info.path or "",
        "typst_version": info.version_text if info.path else "",
        "typst_source": info.source,
        "typst_ok": info.ok,
        "typst_min": ".".join(str(part) for part in MIN_VERSION),
        "typst_bundled_version": manifest.get("version") or "",
        "typst_notes": list(info.notes),
        "packages": package_path(),
        "fonts": font_path(),
        "cache": os.path.join(cache_root(), f"v{manifest.get('version') or '?'}"),
        "compile_cache": compile_cache_path(workspace_root) if workspace_root else "",
        "auto_install": auto_install,
        "mirror": _redact_url(os.environ.get(MIRROR_ENV, "").strip()),
    }


def compile_args(workspace_root: str) -> List[str]:
    """所有 ``typst compile`` 共用的离线/字体参数。"""
    args: List[str] = []
    packages = package_path()
    if packages:
        args += ["--package-path", packages]
    cache = compile_cache_path(workspace_root)
    args += ["--package-cache-path", cache]
    fonts = font_path()
    if fonts:
        args += ["--font-path", fonts]
    return args


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path
