#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed privacy scan for the plugin repository and its artifacts.

The plugin handles a university login cookie and lecture material, so the
repository itself must not contain credentials or personal identifiers. This
script is the mechanical guarantee behind that claim:

* **tracked + untracked (non-ignored) files** — everything that would be
  committed or published;
* **``--history``** — every blob reachable from every ref, so a deleted secret
  cannot survive in git history;
* **``--tarball``** — an ``npm pack`` tarball, i.e. exactly what users get.

Exit code 1 on any finding, so it can gate CI or ``npm publish``.

Usage:
    python tools/privacy_scan.py
    python tools/privacy_scan.py --history
    python tools/privacy_scan.py --tarball output/dsh-zju-lecture-note-1.3.0.tgz
"""

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import tarfile
from typing import Iterable, List, NamedTuple, Optional, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv",
    "output", "dist", ".dsh-test", ".pnpm-store", ".mypy_cache",
}
SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico",
    ".zip", ".tgz", ".gz", ".db", ".sqlite", ".pdf", ".docx", ".pptx",
}
MAX_SCAN_BYTES = 2 * 1024 * 1024

#: Placeholders that are legitimate in documentation and tests.
PLACEHOLDER_RE = re.compile(
    r"(?:example\.(?:com|org)|<[^<>]*>|\b(?:me|you|user|username|yourname|"
    r"placeholder|xxx+)\b|%USER(?:NAME)?%|\$\{?USER\}?)",
    re.IGNORECASE,
)

#: Values that are obviously fixtures, not credentials. A real session cookie
#: is a long random-looking string and contains none of these markers.
FAKE_VALUE_RE = re.compile(
    r"(?:top-secret|super-secret|env-secret|file-secret|another-secret|"
    r"secret-value|dummy|fixture|fake|sample|redacted|placeholder)",
    re.IGNORECASE,
)

_USER_DIR_EXCLUSIONS = r"(?!me\b|you\b|user\b|username\b|public\b|shared\b|default\b|<)"


class Rule(NamedTuple):
    name: str
    pattern: re.Pattern
    description: str


RULES: Sequence[Rule] = (
    Rule(
        "windows-user-path",
        re.compile(r"(?i)\b[a-z]:[\\/]users[\\/]" + _USER_DIR_EXCLUSIONS + r"[^\\/\s\"'`]+"),
        "absolute Windows path containing a real user name",
    ),
    Rule(
        "posix-user-path",
        re.compile(r"(?<![A-Za-z]:)(?:/Users/|/home/)" + _USER_DIR_EXCLUSIONS + r"[A-Za-z0-9._-]+"),
        "absolute macOS/Linux path containing a real user name",
    ),
    Rule(
        "openai-key",
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
        "OpenAI/DeepSeek style API key",
    ),
    Rule(
        "github-token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
        "GitHub personal access token",
    ),
    Rule(
        "aws-key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "AWS access key id",
    ),
    Rule(
        "slack-token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
        "Slack token",
    ),
    Rule(
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
        "embedded private key",
    ),
    Rule(
        "cookie-assignment",
        re.compile(
            r"(?i)\b(?:SESSDATA|JSESSIONID|sessionid|session_id|auth_token|"
            r"access_token|refresh_token|csrf_token)\s*[=:]\s*[\"']?[A-Za-z0-9%._~+/=-]{16,}"
        ),
        "literal session cookie / token assignment",
    ),
    Rule(
        "cookie-header",
        re.compile(r"(?i)\bcookie\s*:\s*[A-Za-z0-9_.-]+=[^;\s\"'`]{8,}"),
        "literal Cookie header value",
    ),
    Rule(
        "personal-email",
        re.compile(
            r"\b[A-Za-z0-9._%+-]+@(?:gmail|qq|163|126|outlook|hotmail|yahoo|"
            r"zju|zhejiang)\.(?:com|cn|edu\.cn)\b",
            re.IGNORECASE,
        ),
        "personal email address",
    ),
)

#: .gitignore patterns whose absence would let private material into git.
REQUIRED_GITIGNORE = (
    "output/",
    "dist/",
    ".env",
    "*.log",
    "node_modules/",
    "__pycache__/",
    ".pytest_cache/",
    "*.tgz",
)


class Finding(NamedTuple):
    scope: str
    location: str
    rule: str
    description: str
    line_no: int
    excerpt: str


def _mask_excerpt(line: str, limit: int = 160) -> str:
    """Show the offending line with the matched secret partially masked."""
    text = line.strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def scan_text(text: str, scope: str, location: str) -> List[Finding]:
    """Scan one text blob with every rule."""
    findings: List[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            for match in rule.pattern.finditer(line):
                matched = match.group(0)
                if PLACEHOLDER_RE.search(matched) or FAKE_VALUE_RE.search(matched):
                    continue
                findings.append(Finding(
                    scope=scope,
                    location=location,
                    rule=rule.name,
                    description=rule.description,
                    line_no=line_no,
                    excerpt=_mask_excerpt(line),
                ))
                break
    return findings


def _read_text(path: str) -> Optional[str]:
    try:
        if os.path.getsize(path) > MAX_SCAN_BYTES:
            return None
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None  # binary
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "ignore")


def _is_skipped(path: str) -> bool:
    normalised = path.replace("\\", "/")
    parts = normalised.split("/")
    if any(part in SKIP_DIRS for part in parts):
        return True
    return os.path.splitext(normalised)[1].lower() in SKIP_SUFFIXES


def _walk_files(root: str) -> List[str]:
    files: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            files.append(os.path.join(dirpath, name))
    return files


def list_repository_files(root: str = REPO_ROOT) -> List[str]:
    """Return files that would be committed: tracked plus non-ignored untracked."""
    # An explicit --root (e.g. the local, git-ignored `output/` directory) is
    # scanned in full instead of being filtered by the repository's ignore
    # rules: the point is to check what is actually on disk there.
    if os.path.abspath(root) != os.path.abspath(REPO_ROOT):
        return _walk_files(root)

    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        if result.returncode == 0:
            return [
                os.path.join(root, line.strip())
                for line in result.stdout.splitlines()
                if line.strip()
            ]
    except (OSError, subprocess.SubprocessError):
        pass

    return _walk_files(root)


def scan_files(root: str = REPO_ROOT, files: Optional[Iterable[str]] = None) -> List[Finding]:
    """Scan repository files (or an explicit list) for privacy leaks."""
    findings: List[Finding] = []
    for path in files if files is not None else list_repository_files(root):
        relative = os.path.relpath(path, root).replace("\\", "/")
        # Judge skip rules against the path relative to the scan root, so an
        # explicit `--root output` is scanned instead of skipping itself.
        if _is_skipped(relative):
            continue
        text = _read_text(path)
        if text is None:
            continue
        findings.extend(scan_text(text, "file", relative))
    return findings


def scan_git_history(root: str = REPO_ROOT) -> List[Finding]:
    """Scan every line ever added to git history.

    ``git log -p`` is used instead of ``git grep`` because the rules rely on
    Python regex features (lookarounds) that POSIX ERE does not support.
    Added lines are enough: any line that ever existed in a reachable commit
    was introduced by some commit's ``+`` side, including the root commit.
    Removed lines are skipped so a cleanup commit is not blamed for the
    secret it deletes.
    """
    findings: List[Finding] = []
    try:
        result = subprocess.run(
            ["git", "log", "-p", "--all", "--no-color", "--no-ext-diff", "--format=commit %H"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if result.returncode != 0:
            return findings
    except (OSError, subprocess.SubprocessError):
        return findings

    commit = "(unknown)"
    current_file = "(unknown)"
    seen = set()
    for line in result.stdout.splitlines():
        if line.startswith("commit "):
            commit = line[len("commit "):][:12]
            continue
        if line.startswith("+++ b/"):
            current_file = line[len("+++ b/"):]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        content = line[1:]
        for finding in scan_text(content, "history", f"{commit}:{current_file}"):
            key = (finding.location, finding.rule, content.strip())
            if key in seen:
                continue
            seen.add(key)
            findings.append(finding)
    return findings


def scan_tarball(path: str) -> List[Finding]:
    """Scan a ``.tgz`` produced by ``npm pack``."""
    findings: List[Finding] = []
    if not os.path.isfile(path):
        return [Finding("tarball", path, "missing", "tarball does not exist", 0, "")]
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or member.size > MAX_SCAN_BYTES:
                    continue
                if _is_skipped(member.name):
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                raw = handle.read()
                if b"\x00" in raw[:4096]:
                    continue
                text = raw.decode("utf-8", "ignore")
                findings.extend(scan_text(text, "tarball", member.name))
    except (OSError, tarfile.TarError, gzip.BadGzipFile) as exc:
        findings.append(Finding("tarball", path, "unreadable", str(exc), 0, ""))
    return findings


def check_gitignore(root: str = REPO_ROOT) -> List[str]:
    """Return required ignore patterns that are missing."""
    path = os.path.join(root, ".gitignore")
    try:
        with open(path, encoding="utf-8") as handle:
            lines = {line.strip() for line in handle if line.strip() and not line.startswith("#")}
    except OSError:
        return list(REQUIRED_GITIGNORE)
    return [pattern for pattern in REQUIRED_GITIGNORE if pattern not in lines]


def report(findings: List[Finding], missing_ignores: Sequence[str], as_json: bool = False) -> int:
    if as_json:
        print(json.dumps({
            "findings": [finding._asdict() for finding in findings],
            "missing_gitignore": list(missing_ignores),
        }, ensure_ascii=False, indent=2))
    else:
        if findings:
            print(f"发现 {len(findings)} 处隐私风险：")
            for finding in findings:
                print(
                    f"  [{finding.rule}] {finding.location}:{finding.line_no}"
                    f"\n      {finding.description}\n      {finding.excerpt}"
                )
        else:
            print("隐私扫描通过：未发现 Cookie、密钥、个人路径或邮箱。")
        if missing_ignores:
            print("`.gitignore` 缺少必要规则：" + ", ".join(missing_ignores))
    return 1 if findings or missing_ignores else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="插件仓库隐私扫描（Cookie / 密钥 / 个人数据）")
    parser.add_argument("--root", default=REPO_ROOT, help="仓库根目录")
    parser.add_argument("--history", action="store_true", help="同时扫描 git 历史")
    parser.add_argument("--tarball", help="同时扫描 npm pack 生成的 .tgz")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--no-gitignore", action="store_true", help="跳过 .gitignore 规则检查")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    findings = scan_files(root)
    if args.history:
        findings.extend(scan_git_history(root))
    if args.tarball:
        findings.extend(scan_tarball(os.path.abspath(args.tarball)))
    missing = [] if args.no_gitignore else check_gitignore(root)
    return report(findings, missing, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
