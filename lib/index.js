/**
 * dsh-zju-lecture-note — DeepSeek Harness 原生插件。
 *
 * 把浙大智云课堂（classroom.zju.edu.cn）回放变成可复习的结构化讲义：
 * 抓语音字幕、投影 PPT、本地课件，产出带时间戳、公式可渲染的讲义。
 *
 * 实现方式：插件注册 8 个原生 dsh 工具，内部复用随包分发的 Python 核心
 * （与 MCP 插件同一份 mcp_server.py），通过 JSON-RPC over stdio 调用，
 * 保证「MCP 插件」与「dsh 插件」的行为完全一致。
 *
 * 隐私约定：插件自身不写用户目录、不收集遥测、不回显 Cookie；随包 Skill
 * 通过 dsh 的技能注册表**在内存中**注册，而不是复制到 $DSH_HOME/skills，
 * 因此安装/卸载都不会在本机留下数据副本。
 */

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { ZjuBridge } from "./bridge.js";
import { ZJU_TOOLS } from "./tools.js";

/**
 * 外部依赖缺失时的处置提示。
 *
 * dsh 插件是 Node ESM 包，裸模块说明符必须能被解析：
 *   - `@deepseek-ai/*` 全部是 peerDependencies：`@deepseek-ai/dsh-*` 由 dsh 运行时提供，
 *     `@deepseek-ai/schemastery` 由 pnpm 在 `dsh plugin add` 时装进 profile 的
 *     node_modules（与 dshmarket 的写法一致）——只把仓库解压出来是没有任何一层的；
 *
 * 直接加载解压出来的目录时，Node 只会抛一句
 * `Cannot find package '@deepseek-ai/schemastery'`，用户看不出该做什么；
 * 这里把它换成能照着做的处置。
 */
const DEPENDENCY_HINTS = {
  "@deepseek-ai/schemastery":
    "插件依赖没装上——它是 peer 依赖，由 pnpm 在 dsh plugin add 时装进 profile 的 node_modules，"
    + "只把解压出来的目录丢给 dsh 加载是装不上的。请改用 dsh 安装（会自动装 peer）："
    + "dsh plugin --profile desktop add github:chenqianyu486-sys/dsh-zju-lecture-note；"
    + "若坚持用本地目录，请先在目录里执行 "
    + "npm install --no-save --no-package-lock @deepseek-ai/schemastery@^3.18.1，再让 dsh 加载。"
    + "（另外确认包名没抄错：正确的是 @deepseek-ai/schemastery，多一个字母就会在 npm 上 404。）",
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
  "适用范围：本段流程仅在处理浙大智云课堂（classroom.zju.edu.cn）回放与讲义任务时适用；其他任务请忽略本段。",
  "处理浙大智云课堂（classroom.zju.edu.cn）回放时，使用本插件提供的 zju_* 工具，并把讲义规范交给 zju-lecture-summarizer Skill。",
  "标准流程：zju_parse_url 解析链接 → zju_fetch_transcript 抓字幕（长课用 view_format=chunked；返回里的 ASR 可靠度低时必须按数学规范复算并在讲义开头写明复核点）→ 可选 zju_fetch_slides / zju_extract_courseware 补充材料 → 用 zju_write_note 写讲义（自动命名 知识总结-<sub_id>-<课程简称>.md、拒绝静默覆盖、写后自动校验）→ 需要时 zju_check_note（fix=true 自动修正）。",
  "讲义里的公式必须符合 Skill 中的「公式书写规范」，否则表格列会被裸竖线截断、公式不会渲染。",
  "隐私边界：登录 Cookie 只存在于 Python 服务进程的内存里，工具不接受 cookie 参数、也不回显明文；不要向用户索要 Cookie 或把它粘贴进对话、文件或命令。",
  "zju_extract_courseware / zju_check_note / zju_write_note 只应指向课件与讲义文件，不要用它们读取凭据、浏览器数据或其他私人文件。",
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
  zju_check_note: { title: "检查/修正讲义渲染规范", kind: "edit" },
  zju_write_note: { title: "写入讲义（自动命名 + 写后校验）", kind: "edit" },
  zju_get_video_url: { title: "解析回放视频直链", kind: "fetch" },
  zju_read_browser_cookie: { title: "读取本机 Edge 登录态", kind: "read" },
};

/**
 * 当前 Agent 的真实工作目录。
 *
 * Python 子进程的 cwd 不可能是 session workspace，所以相对路径（`知识总结.md`）
 * 全靠把这里拿到的目录转发过去。`workingDirectory` 是宿主服务，版本差异下可能不存在，
 * 因此按 session header 里的 cwd 兜底，再兜不住就返回空串（服务端会退回自己的 cwd）。
 *
 * @param {any} ctx 插件上下文
 * @param {any} exec 工具执行上下文
 * @returns {string} 绝对路径，或空串
 */
function sessionCwd(ctx, exec) {
  const session = exec?.agent?.session;
  if (!session) return "";
  try {
    const directory = ctx.get("workingDirectory")?.get(session);
    if (typeof directory === "string" && directory.trim()) return directory.trim();
  } catch {
    /* 服务不可用时用 header 兜底 */
  }
  const header = session.header?.cwd;
  return typeof header === "string" ? header.trim() : "";
}

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
    source: `plugin:${name}`,
    provider: name,
  };
}

/**
 * 找到 `$DSH_HOME/skills/<name>/SKILL.md` 这类同名的磁盘副本。
 *
 * dsh 的技能注册表对同名 skill 只保留一份（按 rank/层级择优，重复的仅打一条
 * warning，不报错），所以旧版插件"把 Skill 复制进用户目录"或用户手动 `cp -r`
 * 留下的副本，可能把插件内置的那一份静默盖掉：Agent 读到的仍是过期 SOP，
 * 而插件更新看起来"没生效"。这里把它显式报出来。
 *
 * @returns {string | null} 磁盘副本的路径
 */
function findShadowingSkillCopy() {
  const roots = [];
  const dshHome = process.env.DSH_HOME?.trim();
  if (dshHome) roots.push(dshHome);
  // dsh 默认把用户级 Skill 放在 ~/.dsh/skills
  if (process.env.USERPROFILE) roots.push(join(process.env.USERPROFILE, ".dsh"));
  if (process.env.HOME) roots.push(join(process.env.HOME, ".dsh"));

  for (const root of roots) {
    const candidate = join(root, "skills", SKILL_NAME, "SKILL.md");
    if (existsSync(candidate) && resolve(candidate) !== resolve(SKILL_FILE)) return candidate;
  }
  return null;
}

/**
 * 同名副本存在时告警：说明哪份生效、内容是否已过期、怎么清理。
 *
 * SKILL.md 的 front matter 只有 name/description，没有 version 字段，
 * 所以"装了旧版 Skill"从版本号上完全看不出来。这里直接比内容哈希并把
 * 两边的 sha256 打出来，用户/Agent 才有据可查，而不是靠"看起来没生效"。
 *
 * @returns {void}
 */
function warnOnShadowingSkillCopy() {
  const shadow = findShadowingSkillCopy();
  if (!shadow) return;
  let stale = true;
  let bundledHash = "?";
  let shadowHash = "?";
  try {
    const bundled = readFileSync(SKILL_FILE);
    const installed = readFileSync(shadow);
    bundledHash = createHash("sha256").update(bundled).digest("hex").slice(0, 12);
    shadowHash = createHash("sha256").update(installed).digest("hex").slice(0, 12);
    stale = !bundled.equals(installed);
  } catch {
    /* 读不了就按"可能过期"提示 */
  }
  process.stderr.write(
    `[zju-lecture] 检测到同名 Skill 的磁盘副本：${shadow}\n`
    + `[zju-lecture] 一个名字只保留一份（重复的只打 warning，不报错），实际生效的不一定是插件里的那份`
    + `${stale ? "——而且这份内容已过期，与插件不一致" : "（这份内容与插件一致，但仍可能盖住插件的更新）"}。\n`
    + `[zju-lecture] 内容哈希：插件 ${bundledHash} / 磁盘副本 ${shadowHash}\n`
    + `[zju-lecture] 让插件内置版本生效：删除目录 ${dirname(shadow)} 后重启 dsh。\n`,
  );
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
      warnOnShadowingSkillCopy();
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
        execute: async (args, exec) => {
          bridge.useWorkspace(sessionCwd(ctx, exec));
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
