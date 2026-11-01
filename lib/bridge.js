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
    this.embedSlideImages = options.embedSlideImages === true;
    this.process = null;
    this.buffer = "";
    this.pending = new Map();
    this.nextId = 1;
    this.starting = null;
    this.lastError = null;
    /**
     * Session workspace, used as the Python child's cwd and exported as
     * ZJU_WORKSPACE. The server is a child process, so its cwd is never the
     * directory the agent works in; without this a relative note path such as
     * `知识总结.md` resolved nowhere and the tool said the file did not exist.
     */
    this.workspace = "";
    this.spawnedWorkspace = null;
    /** 最近 20 行 Python stderr，用于把启动失败的真实原因带进错误消息。 */
    this.stderrTail = [];
  }

  /**
   * Declare the workspace for the next call.
   *
   * The child cannot change its cwd, so a changed workspace recycles the
   * process — but only when nothing is in flight, otherwise an in-flight
   * call would be rejected just to change a directory.
   *
   * @param {string | undefined} directory absolute session workspace
   */
  useWorkspace(directory) {
    const next = typeof directory === "string" ? directory.trim() : "";
    if (!next || next === this.workspace) return;
    this.workspace = next;
  }

  async #spawn(candidate) {
    const cwd = this.workspace && existsSync(this.workspace) ? this.workspace : PLUGIN_ROOT;
    const env = {
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
      PYTHONUNBUFFERED: "1",
      // The plugin setting is authoritative for its own Python child; the
      // env var remains the switch for plain MCP hosts.
      ZJU_EMBED_SLIDES: this.embedSlideImages ? "1" : "0",
    };
    if (cwd !== PLUGIN_ROOT) env.ZJU_WORKSPACE = cwd;
    const child = spawn(candidate.command, [...candidate.args, SERVER_PATH], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      env,
    });
    this.spawnedWorkspace = cwd;

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
      if (!text) return;
      this.stderrTail.push(...text.split(/\r?\n/));
      if (this.stderrTail.length > 20) this.stderrTail = this.stderrTail.slice(-20);
      process.stderr.write(`[zju-lecture] ${text}\n`);
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
    if (this.process) {
      // The workspace moved (another session): recycle only when idle.
      const stale = this.workspace && this.spawnedWorkspace !== this.workspace;
      if (!stale || this.pending.size > 0) return this.process;
      this.dispose();
    }
    if (this.starting) return this.starting;

    this.starting = (async () => {
      if (!existsSync(SERVER_PATH)) {
        throw new Error(`找不到 ZJU Lecture 服务端: ${SERVER_PATH}`);
      }
      const failures = [];
      for (const candidate of pythonCandidates(this.python)) {
        const before = this.stderrTail.length;
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
          // 启动失败时必须清掉 process 引用，否则下一次调用会以为服务端还活着，
          // 直接把请求写进一个已死的 stdin；顺手把 stderr 里的真实原因带出来。
          this.dispose();
          const detail = this.stderrTail.slice(before).join(" | ").trim();
          failures.push(`${candidate.command}: ${error.message}${detail ? ` [stderr] ${detail}` : ""}`);
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

  #request(method, params, timeoutMs = this.timeoutMs) {
    const id = this.nextId++;
    const child = this.process;
    if (!child) return Promise.reject(new Error("ZJU Lecture 服务未运行"));
    const limit = Number(timeoutMs) > 0 ? Number(timeoutMs) : this.timeoutMs;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        // Recycle the Python child only when nothing else is in flight. A
        // timeout used to kill the process and with it the in-memory cookie
        // cache — one slow call silently logged the user out.
        const idle = this.pending.size === 0;
        if (idle) this.dispose();
        const suffix = idle ? "" : "（其他调用仍在进行，服务进程保持运行）";
        reject(new Error(`调用 ${method} 超时（${limit} ms）${suffix}`));
      }, limit);
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
  async call(toolName, args = {}, options = {}) {
    await this.#ensureProcess();
    const response = await this.#request(
      "tools/call",
      {
        name: toolName,
        arguments: args ?? {},
      },
      options.timeoutMs,
    );
    if (response.error) {
      throw new Error(response.error.message || `工具 ${toolName} 调用失败`);
    }

    const result = response.result ?? {};
    const content = result.content;
    let text = null;
    if (Array.isArray(content) && content.length > 0) {
      text = content[0].type === "text" ? content[0].text : JSON.stringify(content[0]);
    }

    // MCP 把工具失败放在 result.isError 上，而不是 JSON-RPC 的 error。
    // 以前先取 text、后判 isError，等于把失败当成功交给宿主：工具调用在 UI 上是绿的，
    // 模型只能从正文里猜"这行字是不是报错"，也就没法触发自动重试/降级。
    if (result.isError === true) {
      throw new Error(text || `工具 ${toolName} 返回错误`);
    }

    if (text !== null) return text;
    return JSON.stringify(result);
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
