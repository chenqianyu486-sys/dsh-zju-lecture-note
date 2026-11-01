/**
 * 端到端：session workspace 必须真的传进 Python 核心（P1-1）。
 *
 * 用法：node tests/bridge_workspace_smoke.mjs
 * 输出：一行 JSON，形如 {"ok":true,"workspace":"...","report":"..."}
 *
 * 场景来自实地反馈：讲义就在工作区根目录，但 Python 子进程的 cwd 不是那里，
 * 于是 `zju_check_note(file_path="知识总结.md")` 报"找不到讲义文件"。
 * 这里把对话式的工作目录交给 bridge，再用相对路径调用一次工具。
 */

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ZjuBridge } from "../lib/bridge.js";

const workspace = mkdtempSync(join(tmpdir(), "zju-workspace-"));
const noteName = "知识总结.md";
writeFileSync(join(workspace, noteName), "# 笔记\n\n正文 $x=1$。\n", "utf8");

const bridge = new ZjuBridge({ timeoutMs: 60000 });
try {
  bridge.useWorkspace(workspace);
  const report = await bridge.call("zju_check_note", { file_path: noteName });
  const missing = await bridge.call("zju_check_note", { file_path: "没有这个文件.md" });
  process.stdout.write(`${JSON.stringify({
    ok: report.includes("讲义渲染规范检查") && !report.includes("找不到讲义文件"),
    spawnedWorkspace: bridge.spawnedWorkspace,
    workspace,
    errorListsCandidates: missing.includes("已尝试") && missing.includes(workspace),
    report: report.split("\n")[0],
  })}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: String(error?.message ?? error) })}\n`);
  process.exitCode = 1;
} finally {
  bridge.dispose();
  // Windows keeps the directory locked while the Python child is still
  // shutting down: a failed cleanup must not turn a passing smoke test red.
  try {
    rmSync(workspace, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
  } catch {
    /* the OS reclaims %TEMP% on its own */
  }
}
