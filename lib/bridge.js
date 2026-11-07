/**
 * Bridge to the bundled ZJU Lecture Python core.
 *
 * The Python side is the very same JSON-RPC stdio server the MCP plugin
 * ships (`mcp_server.py`), so there is exactly one implementation of
 * the ZJU logic and neither plugin form can drift from it.
 */

import { spawn } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PLUGIN_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SERVER_PATH = join(PLUGIN_ROOT, "mcp_server.py");

/** Refused call message: never fall back to the plugin directory. */
export const WORKSPACE_UNAVAILABLE =
  "工作区不可用，已拒绝执行以避免写入插件目录";

/** How many workspace-scoped Python children stay alive at the same time. */
const DEFAULT_MAX_WORKSPACES = 2;

/**
 * Settings copied into the Python child environment at spawn time.
 *
 * A change to any of these cannot reach a running child, so the next call has
 * to start a new one. `timeoutMs` is deliberately absent: it is applied to the
 * JSON-RPC request and does not need a respawn.
 */
const SPAWN_SETTING_KEYS = [
  "python",
  "enableSlides",
  "embedSlideImages",
  "enableStudyNotes",
  "enableLoginTools",
  "renderPdf",
  "typstAutoInstall",
  "typstPath",
  "typstMirror",
];

/**
 * Last-line redaction for Python stderr before it reaches the host log.
 *
 * Python already redacts cookies, but dependency downloads write mirror URLs
 * (userinfo / signed query) straight to stderr. The same text is also kept in
 * `stderrTail`, which is appended to start-up errors returned to the model.
 */
const STDERR_REDACTIONS = [
  // 整个头部值都要吃掉：Cookie 头是 "a=1; b=2"，只替换第一个 token 仍会漏。
  [/(Cookie|Authorization|Bearer)\s*[:=]\s*[^\r\n]+/gi, "$1: [REDACTED]"],
  [/\/\/[^/@\s]+:[^/@\s]+@/g, "//"],
  [/([?&])(token|key|secret|signature)=[^&\s]+/gi, "$1$2=[REDACTED]"],
];

export function redactStderr(text) {
  let value = String(text ?? "");
  for (const [pattern, replacement] of STDERR_REDACTIONS) {
    value = value.replace(pattern, replacement);
  }
  return value;
}

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

/**
 * One Python child per workspace.
 *
 * cwd and `ZJU_WORKSPACE` are fixed at spawn time, so a process is never
 * shared between sessions: session B must not resolve a relative path
 * against session A's directory.
 */
class WorkspaceSession {
  constructor(workspace) {
    this.workspace = workspace;
    this.process = null;
    this.buffer = "";
    this.pending = new Map();
    this.starting = null;
    this.stderrTail = [];
    this.disposed = false;
  }
}

export class ZjuBridge {
  constructor(options = {}) {
    this.python = options.python || "";
    this.timeoutMs = options.timeoutMs || 120000;
    /**
     * Master switch for the optional projection pipeline. The dsh plugin
     * always passes its own setting; direct users of this class keep the
     * pre-1.5.1 default (enabled), matching the Python core's MCP default.
     */
    this.enableSlides = options.enableSlides !== false;
    this.embedSlideImages = this.enableSlides && options.embedSlideImages === true;
    /** Optional fill-in study-note workflow; default true for direct users. */
    this.enableStudyNotes = options.enableStudyNotes !== false;
    /** Optional login helper tools; default true for direct users. */
    this.enableLoginTools = options.enableLoginTools !== false;
    /** Auto-typeset a written note into a reading PDF; off by default. */
    this.renderPdf = options.renderPdf === true;
    /**
     * Download Typst on first use when it is missing (dsh default: on).
     * Direct users keep it on as well unless they set 0, because the whole
     * point is that a fresh machine can typeset without extra steps.
     */
    this.typstAutoInstall = options.typstAutoInstall !== false;
    /**
     * Optional explicit Typst executable and download mirror. Empty keeps the
     * parent environment / built-in lookup order, so a user who never touched
     * these fields sees exactly the pre-2.2.7 behaviour.
     */
    this.typstPath = options.typstPath || "";
    this.typstMirror = options.typstMirror || "";
    this.maxWorkspaces = Math.max(
      1,
      Number(options.maxWorkspaces) > 0 ? Math.floor(Number(options.maxWorkspaces)) : DEFAULT_MAX_WORKSPACES,
    );
    this.nextId = 1;
    this.lastError = null;
    /**
     * Session workspace declared by the host, used as the Python child's cwd
     * and exported as ZJU_WORKSPACE. There is deliberately **no** fallback to
     * PLUGIN_ROOT: a missing workspace means the call is refused, otherwise a
     * relative path could be resolved (and written) inside the plugin.
     */
    this.workspace = "";
    /** Workspace of the most recently spawned child (diagnostics only). */
    this.spawnedWorkspace = null;
    /** workspace key -> WorkspaceSession, insertion order = LRU order. */
    this.sessions = new Map();
    /** 最近 20 行 Python stderr，用于把启动失败的真实原因带进错误消息。 */
    this.stderrTail = [];
  }

  /**
   * Replace the configuration of a live bridge after a settings edit.
   *
   * Every switch below is mirrored into the Python child environment at spawn
   * time, so changing one cannot reach an already-running child. Workspace
   * sessions are therefore dropped when a spawn-affecting value changed; the
   * next tool call spawns a child with the new values. A timeout-only edit
   * keeps the children alive because it only changes the JS request timer.
   * This is what makes a GUI save observable to the agent in the same session
   * instead of only after a full restart.
   *
   * @param {object} options same shape as the constructor options
   * @returns {boolean} whether anything actually changed
   */
  configure(options = {}) {
    const next = {
      python: options.python || "",
      timeoutMs: options.timeoutMs || 120000,
      enableSlides: options.enableSlides !== false,
      embedSlideImages: options.embedSlideImages === true,
      enableStudyNotes: options.enableStudyNotes !== false,
      enableLoginTools: options.enableLoginTools !== false,
      renderPdf: options.renderPdf === true,
      typstAutoInstall: options.typstAutoInstall !== false,
      typstPath: options.typstPath || "",
      typstMirror: options.typstMirror || "",
    };
    const changed = Object.keys(next).some((key) => this[key] !== next[key]);
    const spawnChanged = SPAWN_SETTING_KEYS.some((key) => this[key] !== next[key]);
    Object.assign(this, next);
    if (spawnChanged) this.#disposeSessions();
    return changed;
  }

  /** Drop every workspace session; the next call spawns with current values. */
  #disposeSessions() {
    for (const session of this.sessions.values()) {
      this.#disposeSession(session);
    }
    this.sessions.clear();
  }

  /**
   * Declare the workspace for the next call.
   *
   * A relative path is resolved against the host's process directory exactly
   * once, here, so `call()` always sees an absolute path to validate.
   *
   * @param {string | undefined} directory absolute session workspace
   */
  useWorkspace(directory) {
    const next = typeof directory === "string" ? directory.trim() : "";
    this.workspace = next ? resolve(next) : "";
  }

  #workspaceError(workspace) {
    if (!workspace) {
      return `${WORKSPACE_UNAVAILABLE}: 会话没有声明工作区`;
    }
    try {
      if (!existsSync(workspace) || !statSync(workspace).isDirectory()) {
        return `${WORKSPACE_UNAVAILABLE}: 目录不存在 (${workspace})`;
      }
    } catch {
      return `${WORKSPACE_UNAVAILABLE}: 目录不可访问 (${workspace})`;
    }
    return "";
  }

  #sessionKey(workspace) {
    return process.platform === "win32" ? workspace.toLowerCase() : workspace;
  }

  #sessionFor(workspace) {
    const key = this.#sessionKey(workspace);
    const existing = this.sessions.get(key);
    if (existing) {
      // Re-insert so Map order keeps the least recently used entry first.
      this.sessions.delete(key);
      this.sessions.set(key, existing);
      return existing;
    }
    const session = new WorkspaceSession(workspace);
    this.sessions.set(key, session);
    this.#enforceLimit();
    return session;
  }

  #enforceLimit() {
    while (this.sessions.size > this.maxWorkspaces) {
      let victimKey = null;
      let victim = null;
      for (const [key, session] of this.sessions) {
        if (session.pending.size === 0 && !session.starting) {
          victimKey = key;
          victim = session;
          break;
        }
      }
      if (!victim) {
        const first = this.sessions.entries().next();
        if (first.done) return;
        victimKey = first.value[0];
        victim = first.value[1];
      }
      this.sessions.delete(victimKey);
      this.#disposeSession(victim);
    }
  }

  #killChild(session, reason) {
    const child = session.process;
    session.process = null;
    for (const [, entry] of session.pending) entry.reject(new Error(reason));
    session.pending.clear();
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

  #disposeSession(session) {
    session.disposed = true;
    this.#killChild(session, "ZJU Lecture 服务已关闭（工作区已切换）");
  }

  async #spawn(candidate, session) {
    const env = {
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
      PYTHONUNBUFFERED: "1",
      // The plugin setting is authoritative for its own Python child; the
      // env vars remain the switches for plain MCP hosts.
      ZJU_ENABLE_SLIDES: this.enableSlides ? "1" : "0",
      ZJU_EMBED_SLIDES: this.embedSlideImages ? "1" : "0",
      ZJU_ENABLE_STUDY_NOTES: this.enableStudyNotes ? "1" : "0",
      ZJU_ENABLE_LOGIN_TOOLS: this.enableLoginTools ? "1" : "0",
      ZJU_RENDER_PDF: this.renderPdf ? "1" : "0",
      ZJU_TYPST_AUTO_INSTALL: this.typstAutoInstall ? "1" : "0",
      // Always explicit: the session workspace is the only writable root.
      ZJU_WORKSPACE: session.workspace,
    };
    // An explicit setting wins over an inherited environment variable; an
    // empty field leaves the parent environment (the MCP/CLI fallback) intact.
    if (this.typstPath) env.ZJU_TYPST_BIN = this.typstPath;
    if (this.typstMirror) env.ZJU_TYPST_MIRROR = this.typstMirror;
    const child = spawn(candidate.command, [...candidate.args, SERVER_PATH], {
      cwd: session.workspace,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      env,
    });
    session.process = child;
    this.spawnedWorkspace = session.workspace;

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

    if (session.disposed) {
      try {
        child.kill();
      } catch {
        /* ignore */
      }
      throw new Error("工作区会话已关闭");
    }

    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => this.#onData(session, chunk));
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => {
      const text = redactStderr(String(chunk).trim());
      if (!text) return;
      session.stderrTail.push(...text.split(/\r?\n/));
      if (session.stderrTail.length > 20) session.stderrTail = session.stderrTail.slice(-20);
      this.stderrTail.push(...text.split(/\r?\n/));
      if (this.stderrTail.length > 20) this.stderrTail = this.stderrTail.slice(-20);
      process.stderr.write(`[zju-lecture] ${text}\n`);
    });
    child.on("exit", (code, signal) => {
      if (session.process === child) session.process = null;
      const reason = `Python 服务已退出 (code=${code}, signal=${signal})`;
      for (const [, entry] of session.pending) entry.reject(new Error(reason));
      session.pending.clear();
    });

    return child;
  }

  #onData(session, chunk) {
    session.buffer += chunk;
    let index = session.buffer.indexOf("\n");
    while (index !== -1) {
      const line = session.buffer.slice(0, index).trim();
      session.buffer = session.buffer.slice(index + 1);
      if (line) this.#onLine(session, line);
      index = session.buffer.indexOf("\n");
    }
  }

  #onLine(session, line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    if (!message || typeof message !== "object") return;
    const entry = session.pending.get(message.id);
    if (!entry) return;
    session.pending.delete(message.id);
    entry.resolve(message);
  }

  async #ensureProcess(session) {
    if (session.disposed) throw new Error("ZJU Lecture 工作区会话已关闭");
    if (session.process) return session.process;
    if (session.starting) return session.starting;

    session.starting = (async () => {
      if (!existsSync(SERVER_PATH)) {
        throw new Error(`找不到 ZJU Lecture 服务端: ${SERVER_PATH}`);
      }
      const failures = [];
      for (const candidate of pythonCandidates(this.python)) {
        const before = session.stderrTail.length;
        try {
          const child = await this.#spawn(candidate, session);
          await this.#request(session, "initialize", {
            protocolVersion: "2024-11-05",
            capabilities: {},
            clientInfo: { name: "dsh-zju-lecture-note", version: PLUGIN_VERSION },
          });
          this.#notify(session, "notifications/initialized", {});
          return child;
        } catch (error) {
          // 启动失败时必须清掉 process 引用，否则下一次调用会以为服务端还活着，
          // 直接把请求写进一个已死的 stdin；顺手把 stderr 里的真实原因带出来。
          // 注意这里只杀掉当前子进程，会话本身仍可换下一个解释器重试。
          this.#killChild(session, "ZJU Lecture 服务启动失败");
          const detail = session.stderrTail.slice(before).join(" | ").trim();
          failures.push(`${candidate.command}: ${error.message}${detail ? ` [stderr] ${detail}` : ""}`);
        }
      }
      throw new Error(`无法启动 Python 解释器。已尝试:\n${failures.join("\n")}`);
    })();

    try {
      return await session.starting;
    } finally {
      session.starting = null;
    }
  }

  #write(session, payload) {
    const child = session.process;
    if (!child || child.stdin.destroyed) throw new Error("ZJU Lecture 服务未运行");
    child.stdin.write(`${JSON.stringify(payload)}\n`);
  }

  #notify(session, method, params) {
    this.#write(session, { jsonrpc: "2.0", method, params });
  }

  #request(session, method, params, timeoutMs = this.timeoutMs) {
    const id = this.nextId++;
    const child = session.process;
    if (!child) return Promise.reject(new Error("ZJU Lecture 服务未运行"));
    const limit = Number(timeoutMs) > 0 ? Number(timeoutMs) : this.timeoutMs;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        session.pending.delete(id);
        // Recycle the Python child only when nothing else is in flight. A
        // timeout used to kill the process and with it the in-memory cookie
        // cache — one slow call silently logged the user out.
        const idle = session.pending.size === 0;
        if (idle) this.#disposeSession(session);
        const suffix = idle ? "" : "（其他调用仍在进行，服务进程保持运行）";
        reject(new Error(`调用 ${method} 超时（${limit} ms）${suffix}`));
      }, limit);
      session.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
      this.#write(session, { jsonrpc: "2.0", id, method, params });
    });
  }

  /** Call one MCP tool and return its text payload. */
  async call(toolName, args = {}, options = {}) {
    const workspace = this.workspace;
    const invalid = this.#workspaceError(workspace);
    if (invalid) throw new Error(invalid);

    const session = this.#sessionFor(workspace);
    await this.#ensureProcess(session);
    const response = await this.#request(
      session,
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
    this.#disposeSessions();
  }
}
