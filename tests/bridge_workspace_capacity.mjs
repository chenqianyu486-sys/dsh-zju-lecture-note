/** Busy workspaces must survive temporary overflow of the idle-process limit. */
import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setImmediate } from "node:timers/promises";
import test from "node:test";
import { ZjuBridge } from "../lib/bridge.js";

const args = { url: "https://classroom.zju.edu.cn/livingroom?sub_id=123456" };

async function withWorkspaces(run) {
  const root = mkdtempSync(join(tmpdir(), "zju-capacity-"));
  const directories = ["a", "b", "c"].map((name) => {
    const directory = join(root, name);
    mkdirSync(directory);
    return directory;
  });
  const bridge = new ZjuBridge({ timeoutMs: 10000, typstAutoInstall: false });
  const children = new Map();
  const track = () => {
    for (const session of bridge.sessions.values()) {
      if (session.process && !children.has(session.process)) {
        children.set(session.process, once(session.process, "close"));
      }
    }
  };
  const call = (directory) => {
    bridge.useWorkspace(directory);
    const pending = bridge.call("zju_parse_url", args).then(JSON.parse);
    track();
    return pending;
  };
  try {
    await run({ bridge, directories, call });
  } finally {
    track();
    bridge.dispose();
    await Promise.all(children.values());
    rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}

test("three concurrent cold workspaces all complete and the idle pool shrinks", async () => {
  await withWorkspaces(async ({ bridge, directories, call }) => {
    const results = await Promise.allSettled(directories.map(call));
    for (const result of results) {
      assert.equal(result.status, "fulfilled", result.reason?.message);
      assert.equal(result.value.sub_id, "123456");
    }
    assert.ok(bridge.sessions.size <= 2);
  });
});

test("a third workspace does not evict two busy warm workspaces", async () => {
  await withWorkspaces(async ({ bridge, directories, call }) => {
    await call(directories[0]);
    await call(directories[1]);
    const busyChildren = [...bridge.sessions.values()].map((session) => session.process);
    for (const child of busyChildren) child.stdout.pause();
    const pending = Promise.allSettled(directories.slice(0, 2).map(call));
    await setImmediate();
    let third;
    try {
      third = await call(directories[2]);
    } finally {
      for (const child of busyChildren) child.stdout.resume();
    }
    assert.equal(third.sub_id, "123456");
    for (const result of await pending) {
      assert.equal(result.status, "fulfilled", result.reason?.message);
      assert.equal(result.value.sub_id, "123456");
    }
    assert.ok(bridge.sessions.size <= 2);
  });
});
