/**
 * dsh-zju-lecture-note — DeepSeek Harness 原生插件。
 *
 * 把浙大智云课堂（classroom.zju.edu.cn）回放变成可复习的结构化讲义：
 * 抓语音字幕、投影 PPT、本地课件，产出带时间戳、公式可渲染的讲义。
 *
 * 实现方式：插件注册 7 个原生 dsh 工具，内部复用随包分发的 Python 核心
 * （与 MCP 插件同一份 mcp_server.py），通过 JSON-RPC over stdio 调用，
 * 保证「MCP 插件」与「dsh 插件」的行为完全一致。
 *
 * 隐私约定：插件自身不写用户目录、不收集遥测、不回显 Cookie；随包 Skill
 * 通过 dsh 的技能注册表**在内存中**注册，而不是复制到 $DSH_HOME/skills，
 * 因此安装/卸载都不会在本机留下数据副本。
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { ZjuBridge } from "./bridge.js";
import { ZJU_TOOLS } from "./tools.js";

/**
 * 外部依赖缺失时的处置提示。
 *
 * dsh 插件是 Node ESM 包，裸模块说明符必须能被解析：
 *   - `@deepseek-ai/schemastery` 是本包的普通依赖（dependencies），要由 pnpm
 *     装进 profile 的 node_modules 才会被解析到——只把仓库解压出来是没有的；
 *   - `@deepseek-ai/dsh-*` 由 dsh 运行时提供，不会装进 profile。
 *
 * 直接加载解压出来的目录时，Node 只会抛一句
 * `Cannot find package '@deepseek-ai/schemastery'`，用户看不出该做什么；
 * 这里把它换成能照着做的处置。
 */
const DEPENDENCY_HINTS = {
  "@deepseek-ai/schemastery":
    "请检查两件事：① 包名是否拼对（上游写法是 @deepseek-ai/schemastery，"
    + "多一个字母都会在 npm 上 404）；② 依赖是否装上了 —— "
    + "请用 dsh 安装（会自动装依赖）："
    + "dsh plugin --profile desktop add github:chenqianyu486-sys/dsh-zju-lecture-note；"
    + "若坚持用本地目录，请先在该目录执行 npm install --omit=peer，再让 dsh 加载。",
  "@deepseek-ai/dsh-tools":
    "该包由 DeepSeek Harness 运行时提供，请确认是在 dsh 里启用插件，"
    + "而不是用 node 直接 import 插件目录。",
  "@deepseek-ai/dsh-skill":
    "该包由 DeepSeek Harness 运行时提供，请确认是在 dsh 里启用插件。",
  "@deepseek-ai/dsh-system-prompt":
    "该包由 DeepSeek Harness 运行时提供，请确认是在 dsh 里启用插件。",
};

/**
 * 导入外部依赖；缺依赖时抛出带处置建议的错误，而不是裸的 ERR_MODULE_NOT_FOUND。
 *
 * @param {string} specifier 模块说明符
 * @returns {Promise<any>} 模块命名空间
 */
async function importDependency(specifier) {
  try {
    return await import(specifier);
  } catch (error) {
    const message = String(error?.message ?? error);
    if (error?.code === "ERR_MODULE_NOT_FOUND" && message.includes(specifier)) {
      throw new Error(
        `[dsh-zju-lecture-note] 缺少依赖 ${specifier}。${DEPENDENCY_HINTS[specifier] ?? ""}`
        + `\n原始错误：${message}`,
      );
    }
    throw error;
  }
}

const { default: Schema } = await importDependency("@deepseek-ai/schemastery");
const { defineTool } = await importDependency("@deepseek-ai/dsh-tools");
await importDependency("@deepseek-ai/dsh-skill");
await importDependency("@deepseek-ai/dsh-system-prompt");

const name = "dsh-zju-lecture-note";
const SKILL_NAME = "zju-lecture-summarizer";
const PLUGIN_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SKILL_FILE = join(PLUGIN_ROOT, "skills", SKILL_NAME, "SKILL.md");

const Config = Schema.object({
  python: Schema.string().default(""),
  timeoutMs: Schema.number().min(1000).max(900000).default(120000),
  registerSkill: Schema.boolean().default(true),
});

const SYSTEM_PROMPT = [
  "处理浙大智云课堂（classroom.zju.edu.cn）回放时，使用本插件提供的 zju_* 工具，并把讲义规范交给 zju-lecture-summarizer Skill。",
  "标准流程：zju_parse_url 解析链接 → zju_fetch_transcript 抓字幕（长课用 view_format=chunked）→ 可选 zju_fetch_slides / zju_extract_courseware 补充材料 → 按 Skill 的五段式模板写出 知识总结.md → zju_check_note 校验（fix=true 可自动修正）后再交付。",
  "讲义里的公式必须符合 Skill 中的「公式书写规范」，否则表格列会被裸竖线截断、公式不会渲染。",
  "隐私边界：登录 Cookie 只存在于 Python 服务进程的内存里，工具不接受 cookie 参数、也不回显明文；不要向用户索要 Cookie 或把它粘贴进对话、文件或命令。",
  "zju_extract_courseware / zju_check_note 只应指向课件与讲义文件，不要用它们读取凭据、浏览器数据或其他私人文件。",
].join("\n");

const jsonOutput = {
  schema: { type: "json" },
  render: (_args, value) => [{
    type: "text",
    // The bridge returns plain text wrapped as {text}; surface it as-is so the
    // model and the UI see the transcript / report instead of a JSON envelope.
    text: typeof value === "string" ? value : (value && typeof value.text === "string" ? value.text : JSON.stringify(value)),
  }],
};

/** 每个工具在 UI 上的呈现方式与超时。 */
const TOOL_PRESENT = {
  zju_parse_url: { title: "解析智云课堂回放链接", kind: "read" },
  zju_fetch_transcript: { title: "抓取课堂语音字幕", kind: "fetch" },
  zju_fetch_slides: { title: "抓取课堂投影 PPT", kind: "fetch" },
  zju_extract_courseware: { title: "提取本地课件文本", kind: "read" },
  zju_check_note: { title: "检查讲义渲染规范", kind: "read" },
  zju_get_video_url: { title: "解析回放视频直链", kind: "fetch" },
  zju_read_browser_cookie: { title: "读取本机 Edge 登录态", kind: "read" },
};

/** Split the YAML frontmatter of a SKILL.md file from its body. */
function splitFrontmatter(raw) {
  if (!raw.startsWith("---\n")) return { description: "", body: raw };
  const end = raw.indexOf("\n---", 4);
  if (end === -1) return { description: "", body: raw };
  const front = raw.slice(4, end);
  const body = raw.slice(end + 4).replace(/^\s*\n/, "");
  let description = "";
  for (const line of front.split("\n")) {
    if (line.startsWith("description:")) {
      description = line.slice("description:".length).trim();
      break;
    }
  }
  return { description, body };
}

/**
 * Read the bundled skill for in-memory registration.
 *
 * The plugin is installed under a pnpm store path, so the skill file ships
 * inside the package and is read from there; nothing is copied into the user's
 * home directory.
 */
function readBundledSkill() {
  if (!existsSync(SKILL_FILE)) return null;
  const raw = readFileSync(SKILL_FILE, "utf8");
  const { description, body } = splitFrontmatter(raw);
  return {
    name: SKILL_NAME,
    description: description || "整理浙大智云课堂回放为结构化讲义",
    content: body,
    path: SKILL_FILE,
    provider: name,
  };
}

function apply(ctx, config) {
  const bridge = new ZjuBridge({
    python: config.python,
    timeoutMs: config.timeoutMs,
  });
  ctx.effect(() => () => bridge.dispose());

  if (config.registerSkill) {
    const skill = readBundledSkill();
    if (skill) {
      // Registration is synchronous, so it lands during apply() as the skill
      // registry expects. Disposal is owned by the plugin fiber.
      ctx.inject(["skills"], (ctx) => {
        ctx.skills.register(skill);
      });
    } else {
      process.stderr.write(`[zju-lecture] 未找到随包 Skill: ${SKILL_FILE}\n`);
    }
  }

  ctx.inject(["tools"], (ctx) => {
    for (const tool of ZJU_TOOLS) {
      const present = TOOL_PRESENT[tool.name] || { title: tool.name, kind: "read" };
      ctx.tools.register(defineTool({
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters,
        timeoutMs: config.timeoutMs,
        presentCall: () => ({
          card: "generic",
          title: present.title,
          kind: present.kind,
        }),
        output: jsonOutput,
        execute: async (args) => {
          const text = await bridge.call(tool.name, args ?? {});
          return { text };
        },
      }));
    }
  });

  ctx.inject(["systemPrompt"], (ctx) => {
    ctx.effect(() => {
      const dispose = ctx.systemPrompt.section({
        name,
        order: 72,
        interpolate: false,
        text: SYSTEM_PROMPT,
      });
      return () => {
        if (typeof dispose === "function") dispose();
      };
    });
  });
}

export { Config, SYSTEM_PROMPT, apply, name, splitFrontmatter };
