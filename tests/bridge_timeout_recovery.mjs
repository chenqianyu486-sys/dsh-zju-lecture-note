/** Real Python bridge regressions: timeout recovery and stale child events. */
import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setImmediate } from "node:timers/promises";
import test from "node:test";

import { ZjuBridge } from "../lib/bridge.js";

const SAMPLE = {
  url: "https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456",
};

async function withBridge(run) {
  const workspace = mkdtempSync(join(tmpdir(), "zju-timeout-recovery-"));
  const bridge = new ZjuBridge({
    timeoutMs: 10000,
    renderPdf: false,
    typstAutoInstall: false,
  });
  bridge.useWorkspace(workspace);
  const children = new Map();
  const track = (child) => {
    if (!children.has(child)) children.set(child, once(child, "close"));
    return child;
  };
  try {
    await run(bridge, track);
  } finally {
    for (const session of bridge.sessions.values()) {
      if (session.process) track(session.process);
    }
    bridge.dispose();
    await Promise.all(children.values());
    rmSync(workspace, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}

async function parse(bridge, options) {
  return JSON.parse(await bridge.call("zju_parse_url", SAMPLE, options));
}

test("the same workspace recovers after its only request times out", async () => {
  await withBridge(async (bridge, track) => {
    assert.equal((await parse(bridge)).sub_id, "123456");
    const child = track([...bridge.sessions.values()][0].process);
    // Hold a real Python response in the pipe to reproduce a slow transport.
    child.stdout.pause();
    await assert.rejects(parse(bridge, { timeoutMs: 20 }), /超时/);
    assert.equal((await parse(bridge)).sub_id, "123456");
  });
});

test("an old child's exit cannot reject a replacement child's request", async () => {
  await withBridge(async (bridge, track) => {
    await parse(bridge);
    const session = [...bridge.sessions.values()][0];
    const oldChild = track(session.process);
    const closed = once(oldChild, "close");
    oldChild.kill();
    await closed;
    assert.equal((await parse(bridge)).sub_id, "123456");
    const replacement = session.process;
    replacement.stdout.pause();
    const pending = parse(bridge);
    const settled = assert.doesNotReject(pending);
    await setImmediate();
    // Deliver a delayed lifecycle callback while the real new request is pending.
    oldChild.emit("exit", 9, null);
    replacement.stdout.resume();
    await settled;
    assert.equal((await pending).sub_id, "123456");
  });
});

test("an old child's partial stdout cannot corrupt a replacement response", async () => {
  await withBridge(async (bridge, track) => {
    await parse(bridge);
    const session = [...bridge.sessions.values()][0];
    const oldChild = track(session.process);
    const closed = once(oldChild, "close");
    oldChild.kill();
    await closed;
    await parse(bridge);
    track(session.process);
    // Late bytes from an obsolete pipe must never enter the new JSON buffer.
    oldChild.stdout.emit("data", "unfinished-old-response");
    assert.equal((await parse(bridge, { timeoutMs: 200 })).sub_id, "123456");
  });
});

test("a restarted child does not inherit an incomplete response buffer", async () => {
  await withBridge(async (bridge, track) => {
    await parse(bridge);
    const child = track([...bridge.sessions.values()][0].process);
    child.stdout.emit("data", "unfinished-before-exit");
    const closed = once(child, "close");
    child.kill();
    await closed;
    bridge.timeoutMs = 1000;
    assert.equal((await parse(bridge)).sub_id, "123456");
  });
});
