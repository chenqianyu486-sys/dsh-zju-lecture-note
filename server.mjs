#!/usr/bin/env node
/**
 * Launcher for the ZJU Lecture MCP server.
 *
 * The MCP server itself is implemented in Python (standard library only), so
 * this launcher resolves a usable interpreter at runtime and then pipes stdio
 * through to it. That keeps one cross-platform command (`node`) in the
 * plugin manifest while still working on hosts where only `python3` exists
 * and on hosts where only `python` exists.
 */

import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const serverScript = path.join(here, 'mcp_server.py');
const MIN_PYTHON = [3, 9];

const CANDIDATES = [
  { command: 'python3', args: [] },
  { command: 'python', args: [] },
  { command: 'py', args: ['-3'] },
];

// An explicit interpreter (same variable the dsh plugin honours) wins.
if (process.env.ZJU_PYTHON && process.env.ZJU_PYTHON.trim()) {
  CANDIDATES.unshift({ command: process.env.ZJU_PYTHON.trim(), args: [] });
}

function parseVersion(text) {
  const match = String(text || '').match(/(\d+)\.(\d+)/);
  if (!match) return null;
  return [Number(match[1]), Number(match[2])];
}

function probe(candidate) {
  try {
    const result = spawnSync(candidate.command, [...candidate.args, '--version'], {
      encoding: 'utf8',
      timeout: 20000,
      windowsHide: true,
    });
    if (result.error || result.status !== 0) return null;
    const version = parseVersion(result.stdout || result.stderr);
    if (!version) return null;
    if (version[0] < MIN_PYTHON[0] || (version[0] === MIN_PYTHON[0] && version[1] < MIN_PYTHON[1])) {
      return null;
    }
    return { ...candidate, version: version.join('.') };
  } catch {
    return null;
  }
}

function resolvePython() {
  for (const candidate of CANDIDATES) {
    const resolved = probe(candidate);
    if (resolved) return resolved;
  }
  return null;
}

function fail(message) {
  process.stderr.write(`[zju-lecture] ${message}\n`);
  process.exit(1);
}

if (!existsSync(serverScript)) {
  fail(`找不到 MCP 服务器脚本：${serverScript}`);
}

const python = resolvePython();
if (!python) {
  fail(
    '未找到可用的 Python 3.9+ 解释器（尝试过 python3 / python / py -3）。\n' +
      '请安装 Python 3.9 或更高版本并确保它在 PATH 中，然后重试。',
  );
}

const child = spawn(python.command, [...python.args, serverScript], {
  stdio: ['pipe', 'pipe', 'pipe'],
  windowsHide: true,
  env: {
    ...process.env,
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    PYTHONUNBUFFERED: '1',
  },
});

process.stderr.write(`[zju-lecture] MCP server starting with ${python.command} (Python ${python.version})\n`);

child.stdout.on('error', () => {});
child.stderr.on('error', () => {});
child.stdout.pipe(process.stdout);
child.stderr.pipe(process.stderr);

process.stdin.on('error', () => {});
process.stdin.pipe(child.stdin);

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, () => {
    if (!child.killed) child.kill(signal);
  });
}

child.on('exit', (code, signal) => {
  if (signal) {
    process.exit(1);
  }
  process.exit(code === null ? 0 : code);
});

child.on('error', (error) => {
  fail(`启动 Python 进程失败：${error && error.message ? error.message : String(error)}`);
});
