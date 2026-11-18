/**
 * 回归：超时后会话必须能重建，旧子进程的延迟事件不能污染新请求。
 *
 * 旧实现里 #disposeSession 只置 disposed 却不把会话从缓存摘除，下次取回已关闭
 * 会话会永久抛「会话已关闭」；崩溃后在同一会话上 respawn 时，旧子进程延迟到达的
 * exit / stdout 还会拒绝或串改新进程的在途请求。
 *
 * 用法：node tests/bridge_timeout_recovery.mjs
 * 输出：一行 JSON，形如 {"ok":true,"message":"..."}；不联网、结果确定。
 */

import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setImmediate } from "node:timers/promises";

import { ZjuBridge } from "../lib/bridge.js";

const SAMPLE = { url: "https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456" };
const workspace = mkdtempSync(join(tmpdir(), "zju-timeout-recovery-"));
const bridge = new ZjuBridge({ timeoutMs: 10000 });
const children = new Map();
const track = (child) => {
  if (child && !children.has(child)) children.set(child, once(child, "close"));
  return child;
};
const parse = (options) => bridge.call("zju_parse_url", SAMPLE, options).then(JSON.parse);
const payload = { ok: false, message: "" };

try {
  bridge.useWorkspace(workspace);

  // 1) 唯一请求超时后，同一工作区必须能恢复，而不是永久砖化。
  assert.equal((await parse()).sub_id, "123456");
  const first = track([...bridge.sessions.values()][0].process);
  first.stdout.pause();
  await assert.rejects(parse({ timeoutMs: 20 }), /超时/);
  assert.equal((await parse()).sub_id, "123456");

  // 2) 旧子进程延迟到达的 exit 不能拒绝替换进程持有的在途请求。
  const session = [...bridge.sessions.values()][0];
  const old = track(session.process);
  const closed = once(old, "close");
  old.kill();
  await closed;
  assert.equal((await parse()).sub_id, "123456");
  const replacement = session.process;
  replacement.stdout.pause();
  const pending = parse();
  await setImmediate();
  old.emit("exit", 9, null);
  replacement.stdout.resume();
  assert.equal((await pending).sub_id, "123456");

  // 3) 旧子进程的残留 stdout 不能串进新进程的响应缓冲。
  const stale = track(session.process);
  const closedAgain = once(stale, "close");
  stale.kill();
  await closedAgain;
  await parse();
  track(session.process);
  stale.stdout.emit("data", "unfinished-old-response");
  assert.equal((await parse({ timeoutMs: 500 })).sub_id, "123456");

  payload.ok = true;
  payload.message = "timeout recovery + stale child isolation";
} catch (error) {
  payload.message = String(error?.stack ?? error);
} finally {
  for (const session of bridge.sessions.values()) track(session.process);
  bridge.dispose();
  await Promise.all(children.values());
  try {
    rmSync(workspace, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  } catch {
    /* the OS reclaims %TEMP% on its own */
  }
}

process.stdout.write(`${JSON.stringify(payload)}\n`);
process.exitCode = payload.ok ? 0 : 1;