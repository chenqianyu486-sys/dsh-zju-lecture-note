/**
 * Bridge to the bundled ZJU Lecture Python core.
 *
 * The Python side is the very same JSON-RPC stdio server the MCP plugin
 * ships (`mcp_server.py`), so there is exactly one implementation of
 * the ZJU logic and neither plugin form can drift from it.
 */

import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PLUGIN_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SERVER_PATH = join(PLUGIN_ROOT, "mcp_server.py");

const PLUGIN_VERSION = (() => {
  try {
    return JSON.parse(readFileSync(join(PLUGIN_ROOT, "package.json"), "utf8")).version || "0.0.0";
  } catch {
    return "0.0.0";
  }
})();

/**
 * Interpreters to try, in order.
 *
 * The DeepSeek Harness ships its own Python next to the runtime that hosts
 * this plugin, so the bundled interpreter is preferred over whatever happens
 * to be on PATH.
 */
export function pythonCandidates(explicit) {
  const candidates = [];
  if (explicit && explicit.trim()) {
    candidates.push({ command: explicit.trim(), args: [] });
  }
  if (process.env.ZJU_PYTHON && process.env.ZJU_PYTHON.trim()) {
    candidates.push({ command: process.env.ZJU_PYTHON.trim(), args: [] });
  }

  const execDir = dirname(process.execPath || "");
  const bundled = join(
    execDir,
    "resources",
    "runtime",
    "primary-runtime",
    "dependencies",
    "python",
    process.platform === "win32" ? "python.exe" : "bin/python3",
  );
  if (execDir && existsSync(bundled)) {
    candidates.push({ command: bundled, args: [] });
  }

  if (process.platform === "win32") {
    candidates.push({ command: "py", args: ["-3"] });
    candidates.push({ command: "python", args: [] });
    candidates.push({ command: "python3", args: [] });
  } else {
    candidates.push({ command: "python3", args: [] });
    candidates.push({ command: "python", args: [] });
  }

  return candidates;
}

export class ZjuBridge {
  constructor(options = {}) {
    this.python = options.python || "";
    this.timeoutMs = options.timeoutMs || 120000;
    this.process = null;
    this.buffer = "";
    this.pending = new Map();
    this.nextId = 1;
    this.starting = null;
    this.lastError = null;
  }

  async #spawn(candidate) {
    const child = spawn(candidate.command, [...candidate.args, SERVER_PATH], {
      cwd: PLUGIN_ROOT,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONUTF8: "1",
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1",
      },
    });

    await new Promise((done, fail) => {
      let settled = false;
      const onError = (error) => {
        if (settled) return;
        settled = true;
        fail(error);
      };
      child.once("error", onError);
      child.once("spawn", () => {
        if (settled) return;
        settled = true;
        child.off("error", onError);
        done();
      });
    });

    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => this.#onData(chunk));
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => {
      const text = String(chunk).trim();
      if (text) process.stderr.write(`[zju-lecture] ${text}\n`);
    });
    child.on("exit", (code, signal) => {
      this.process = null;
      const reason = `Python 服务已退出 (code=${code}, signal=${signal})`;
      for (const [, entry] of this.pending) entry.reject(new Error(reason));
      this.pending.clear();
    });

    return child;
  }

  #onData(chunk) {
    this.buffer += chunk;
    let index = this.buffer.indexOf("\n");
    while (index !== -1) {
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (line) this.#onLine(line);
      index = this.buffer.indexOf("\n");
    }
  }

  #onLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    if (!message || typeof message !== "object") return;
    const entry = this.pending.get(message.id);
    if (!entry) return;
    this.pending.delete(message.id);
    entry.resolve(message);
  }

  async #ensureProcess() {
    if (this.process) return this.process;
    if (this.starting) return this.starting;

    this.starting = (async () => {
      if (!existsSync(SERVER_PATH)) {
        throw new Error(`找不到 ZJU Lecture 服务端: ${SERVER_PATH}`);
      }
      const failures = [];
      for (const candidate of pythonCandidates(this.python)) {
        try {
          const child = await this.#spawn(candidate);
          this.process = child;
          await this.#request("initialize", {
            protocolVersion: "2024-11-05",
            capabilities: {},
            clientInfo: { name: "dsh-zju-lecture-note", version: PLUGIN_VERSION },
          });
          this.#notify("notifications/initialized", {});
          return child;
        } catch (error) {
          failures.push(`${candidate.command}: ${error.message}`);
        }
      }
      throw new Error(`无法启动 Python 解释器。已尝试:\n${failures.join("\n")}`);
    })();

    try {
      return await this.starting;
    } finally {
      this.starting = null;
    }
  }

  #write(payload) {
    const child = this.process;
    if (!child || child.stdin.destroyed) throw new Error("ZJU Lecture 服务未运行");
    child.stdin.write(`${JSON.stringify(payload)}\n`);
  }

  #notify(method, params) {
    this.#write({ jsonrpc: "2.0", method, params });
  }

  #request(method, params) {
    const id = this.nextId++;
    const child = this.process;
    if (!child) return Promise.reject(new Error("ZJU Lecture 服务未运行"));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        this.dispose();
        reject(new Error(`调用 ${method} 超时（${this.timeoutMs} ms）`));
      }, this.timeoutMs);
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
      this.#write({ jsonrpc: "2.0", id, method, params });
    });
  }

  /** Call one MCP tool and return its text payload. */
  async call(toolName, args = {}) {
    await this.#ensureProcess();
    const response = await this.#request("tools/call", {
      name: toolName,
      arguments: args ?? {},
    });
    if (response.error) {
      throw new Error(response.error.message || `工具 ${toolName} 调用失败`);
    }
    const content = response.result?.content;
    if (Array.isArray(content) && content.length > 0) {
      if (content[0].type === "text") return content[0].text;
      return JSON.stringify(content[0]);
    }
    if (response.result?.isError) {
      throw new Error(typeof content?.[0]?.text === "string" ? content[0].text : "工具返回错误");
    }
    return JSON.stringify(response.result ?? null);
  }

  dispose() {
    const child = this.process;
    this.process = null;
    for (const [, entry] of this.pending) entry.reject(new Error("ZJU Lecture 服务已关闭"));
    this.pending.clear();
    if (!child) return;
    try {
      child.stdin.end();
    } catch {
      /* ignore */
    }
    try {
      child.kill();
    } catch {
      /* ignore */
    }
  }
}
