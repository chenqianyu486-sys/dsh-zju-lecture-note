/**
 * 会话工作区隔离：两个 dsh 会话并发时，绝不能共用一个 Python 子进程。
 *
 * 用法：node tests/bridge_workspace_isolation.mjs
 * 输出：一行 JSON，形如 {"ok":true,"sessions":2,...}
 *
 * 场景来自安全审查 7.1：会话 A 有在途调用时，会话 B 切换工作区，
 * 旧实现因为 `pending.size > 0` 拒绝重启，B 的相对路径于是按 A 的
 * cwd / ZJU_WORKSPACE 解析。这里让 A 的调用保持"在途"（不 await），
 * 立刻切换 B 并发起调用，再从两边报告里核对各自的工作区与进程身份。
 */

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ZjuBridge, WORKSPACE_UNAVAILABLE } from "../lib/bridge.js";

const workspaceA = mkdtempSync(join(tmpdir(), "zju-iso-a-"));
const workspaceB = mkdtempSync(join(tmpdir(), "zju-iso-b-"));
const missing = join(workspaceA, "does-not-exist");

const bridge = new ZjuBridge({ timeoutMs: 60000 });
const payload = { ok: false };
try {
  // A 的调用故意不 await：调用创建的瞬间就把 A 的进程/请求算作在途。
  bridge.useWorkspace(workspaceA);
  const callA = bridge.call("zju_doctor", {});
  // 会话 B 紧接着切换工作区；旧实现会继续复用 A 的子进程。
  bridge.useWorkspace(workspaceB);
  const callB = bridge.call("zju_doctor", {});

  const [reportA, reportB] = await Promise.all([callA, callB]);

  const sessions = [...bridge.sessions.values()];
  const byWorkspace = new Map(sessions.map((session) => [session.workspace, session]));
  const sessionA = byWorkspace.get(workspaceA);
  const sessionB = byWorkspace.get(workspaceB);

  const hasOwn = (report, workspace) =>
    report.toLowerCase().includes(workspace.toLowerCase());
  const leaked = (report, other) =>
    report.toLowerCase().includes(other.toLowerCase());

  // 工作区缺失/不存在时必须拒绝，而不是退回插件目录。
  bridge.useWorkspace("");
  let missingWorkspaceError = "";
  try {
    await bridge.call("zju_doctor", {});
  } catch (error) {
    missingWorkspaceError = String(error?.message ?? error);
  }
  bridge.useWorkspace(missing);
  let nonexistentError = "";
  try {
    await bridge.call("zju_doctor", {});
  } catch (error) {
    nonexistentError = String(error?.message ?? error);
  }

  payload.ok =
    Boolean(sessionA && sessionB) &&
    sessionA !== sessionB &&
    sessionA.process !== sessionB.process &&
    hasOwn(reportA, workspaceA) &&
    !leaked(reportA, workspaceB) &&
    hasOwn(reportB, workspaceB) &&
    !leaked(reportB, workspaceA) &&
    missingWorkspaceError.includes(WORKSPACE_UNAVAILABLE) &&
    nonexistentError.includes(WORKSPACE_UNAVAILABLE);
  payload.sessions = sessions.length;
  payload.distinctProcesses = Boolean(sessionA && sessionB && sessionA.process !== sessionB.process);
  payload.reportAHasA = hasOwn(reportA, workspaceA);
  payload.reportAHasB = leaked(reportA, workspaceB);
  payload.reportBHasB = hasOwn(reportB, workspaceB);
  payload.reportBHasA = leaked(reportB, workspaceA);
  payload.missingWorkspaceError = missingWorkspaceError;
  payload.nonexistentError = nonexistentError;
} catch (error) {
  payload.error = String(error?.message ?? error);
  process.exitCode = 1;
} finally {
  bridge.dispose();
  for (const directory of [workspaceA, workspaceB]) {
    try {
      rmSync(directory, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
    } catch {
      /* Windows 会稍后回收 %TEMP% */
    }
  }
}

process.stdout.write(`${JSON.stringify(payload)}\n`);
if (!payload.ok && !payload.error) process.exitCode = 1;
