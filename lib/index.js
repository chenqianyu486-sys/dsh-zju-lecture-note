/**
 * dsh-zju-lecture-note — DeepSeek Harness 原生插件。
 *
 * 把浙大智云课堂（classroom.zju.edu.cn）回放变成可复习的结构化讲义：
 * 以语音字幕 + 本地课件为主链路；投影 PPT 截图是可选模块，由 `enableSlides` 开关。
 * 产出带时间戳、公式可渲染的讲义。
 *
 * 实现方式：插件最多注册 10 个原生 dsh 工具（默认只注册 6 个核心工具，可选模块按设置打开），
 * 内部复用随包分发的 Python 核心（与 MCP 插件同一份 mcp_server.py），
 * 通过 JSON-RPC over stdio 调用，保证「MCP 插件」与「dsh 插件」的行为完全一致。
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
const PLUGIN_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const SKILL_NAME = "zju-lecture-summarizer";

/**
 * The projection appendix of the transcript skill.
 *
 * It is appended to the in-memory skill only when `enableSlides` is on, so a
 * transcript-only session never sees instructions for a tool that was not
 * registered.
 */
const SLIDES_SKILL_FILE = join(PLUGIN_ROOT, "skills", SKILL_NAME, "SLIDES.md");

/**
 * The skills this plugin ships.
 *
 * `zju-lecture-summarizer` is the transcript SOP. Its `SLIDES.md` appendix is
 * appended to the in-memory skill only when `enableSlides` is on, so a
 * transcript-only session never sees instructions for a tool that was not
 * registered.
 *
 * `scholia-notes` is the fill-in study-note workflow: it turns a lecture note
 * into a Typst notebook with blanks (see `zju_build_study_notes`). It has no
 * appendix and no feature gate.
 */
const SKILL_SPECS = [
  {
    name: SKILL_NAME,
    fallbackDescription: "整理浙大智云课堂回放为结构化讲义",
    when: "always",
    appendices: [{ path: SLIDES_SKILL_FILE, when: "slides" }],
  },
  {
    name: "scholia-notes",
    fallbackDescription: "把 STEM 讲义排成填空式学习笔记（Typst → PDF）",
    when: "study",
    appendices: [],
  },
];

/** Directory of one bundled skill. */
function skillDir(skillName) {
  return join(PLUGIN_ROOT, "skills", skillName);
}

const Config = Schema.object({
  python: Schema.string().default(""),
  timeoutMs: Schema.number().min(1000).max(900000).default(120000),
  registerSkill: Schema.boolean().default(true),
  renderPdf: Schema.boolean()
    .description(
      "写入讲义后自动排成同名 PDF（默认开启）：让阅读体验从 Markdown 提升到可打印的讲义。"
      + "需要本机安装 Typst（≥0.13）；没装或排版失败时 Markdown 照常保存，只跳过 PDF。"
      + "这一项不会多花模型 token：排版在本地完成，工具只回一行路径。",
    )
    .default(true)
    .volatile(),
  enableStudyNotes: Schema.boolean()
    .description(
      "启用「填空式学习笔记」模块（默认关闭）：注册 zju_build_study_notes 并加载 scholia-notes Skill。"
      + "它把讲义再加工成可动手填写的复习笔记；只要普通讲义 PDF 的话不必开启。",
    )
    .default(false)
    .volatile(),
  enableSlides: Schema.boolean()
    .description(
      "启用「PPT 投影抓取」可选模块（默认关闭）：开启后注册 zju_fetch_slides，"
      + "可从课堂回放抓取投影截图并合成 PDF。关闭时插件只走「语音字幕 + 本地课件」链路，"
      + "不注册投影工具、不读取浏览器登录态、不下载截图；字幕接口本身公开免登录。",
    )
    .default(false)
    .volatile(),
  embedSlideImages: Schema.boolean()
    .description(
      "把投影截图引用进讲义（需先开启「PPT 投影抓取」；默认关闭，节省下载时间与视觉 token）",
    )
    .default(false)
    .volatile(),
  enableLoginTools: Schema.boolean()
    .description(
      "启用登录辅助工具（默认关闭）：zju_get_video_url 解析视频直链、"
      + "zju_read_browser_cookie 读取本机 Edge 登录态。投影抓取会自行解析登录态，"
      + "不依赖这两个工具；只有需要下载视频或 Whisper 重识别时才打开。",
    )
    .default(false)
    .volatile(),
  typstAutoInstall: Schema.boolean()
    .description(
      "缺少 Typst 时自动下载并安装（默认开启）：从 GitHub 官方 Release 下载当前平台的"
      + " Typst（约 20 MB，Apache-2.0），按仓库内固定的 SHA256 校验后装到用户缓存目录。"
      + "关闭后只提示安装命令，不联网、不写盘。",
    )
    .default(true)
    .volatile(),
});

/** Optional tool groups; every other tool belongs to the always-on transcript core. */
const SLIDE_TOOL_NAMES = new Set(["zju_fetch_slides"]);
const STUDY_TOOL_NAMES = new Set(["zju_build_study_notes"]);
const LOGIN_TOOL_NAMES = new Set(["zju_get_video_url", "zju_read_browser_cookie"]);

/**
 * Read one plugin setting.
 *
 * dsh projects every `Config` field marked `.volatile()` as a live reference
 * (`{ get() }`) instead of a primitive, so the plugin can follow settings
 * edits without a restart. Comparing that reference to `true` is always
 * false — which silently turned every optional module off no matter what the
 * user saved. Unwrap defensively because the same object is also built by
 * tests and direct callers as a plain value.
 *
 * @param {object} config plugin config (or `{}`)
 * @param {string} key field name
 * @returns {unknown} the current value, or `undefined`
 */
function readSetting(config, key) {
  const raw = config?.[key];
  if (raw && typeof raw === "object" && typeof raw.get === "function") {
    try {
      return raw.get();
    } catch {
      return undefined;
    }
  }
  return raw;
}

/**
 * Normalise one configuration into the booleans the rest of the plugin uses.
 *
 * Defaults matter because the same object is built by dsh (which applies the
 * schema defaults) and by tests / direct users (which may omit a field):
 * reading PDF is on unless explicitly off; the optional modules are off
 * unless explicitly on.
 */
function featureFlags(config = {}) {
  const value = (key) => readSetting(config, key);
  const enableSlides = value("enableSlides") === true;
  return {
    renderPdf: value("renderPdf") !== false,
    enableStudyNotes: value("enableStudyNotes") === true,
    enableSlides,
    embedSlideImages: enableSlides && value("embedSlideImages") === true,
    enableLoginTools: value("enableLoginTools") === true,
    typstAutoInstall: value("typstAutoInstall") !== false,
  };
}

/** Which tools are registered for one configuration. */
function registerableTools(config = {}) {
  const flags = typeof config === "boolean"
    ? { ...featureFlags({}), enableSlides: config }
    : featureFlags(config);
  return ZJU_TOOLS.filter((tool) => {
    if (SLIDE_TOOL_NAMES.has(tool.name)) return flags.enableSlides;
    if (STUDY_TOOL_NAMES.has(tool.name)) return flags.enableStudyNotes;
    if (LOGIN_TOOL_NAMES.has(tool.name)) return flags.enableLoginTools;
    return true;
  });
}

/** Downloading a full deck of screenshots legitimately exceeds the default. */
const SLOW_TOOL_TIMEOUT_MS = 600000;

/** Typst compiles a notebook and renders every page to PNG: also slow. */
const COMPILE_TOOL_TIMEOUT_MS = 300000;

const SYSTEM_PROMPT = [
  "适用范围：仅处理浙大智云课堂（classroom.zju.edu.cn）回放与讲义任务；其他任务请忽略本段。",
  "主链路：把链接或 sub_id 直接交给 zju_fetch_transcript（默认 per_minute；长课 chunked；同一节课只抓一次，per_segment 仅在确实需要秒级时间戳时用）→ 可选 zju_extract_courseware → zju_write_note 一次写入。write_note 会自动命名、拒绝静默覆盖、修公式、校验，并按设置自动排版同名 PDF；不要再调 zju_parse_url，也不要对同一份讲义重复调 zju_check_note。",
  "讲义默认按「复习版」写：每节保留 [HH:MM]；老师讲过的例题整理成「题目 → 切入点 → 关键步骤 → 易错点」，本节没有例题就写「本节无例题」，不要编题；文末给 3–5 道自测题（答案用多行 <details> 折叠）与 5–10 条考点预测。",
  "例题/定理/定义/证明要写成行首标记（[例] 标题 —— 正文 / [定理] … / [定义] … / [证明] …），"
    + "不要写成 `#### 例 1：…` 或 `**证明**`——那种写法在 PDF 里只是小标题和粗体，排不出方框（工具会报 pseudo_box 警告）。",
  "用户只说「整理这节课」时按完整链路一次做完，不要只交字幕摘要；只有明确说「只要速记 / 只要 Markdown」时才省略这些增强内容。",
  "ASR 可靠度低时按 Skill 的数学规范复算，并在讲义开头写明需要人工复核的时间点；公式必须符合 Skill 的「公式书写规范」。",
  "交付时给出 Markdown 路径；有 PDF 时一并给出 PDF 路径。不要声称看过自己无法查看的图片。",
  "隐私边界：登录 Cookie 只在 Python 进程内存里，工具不接受、也不回显 Cookie 明文；不要向用户索要 Cookie，或把它写进对话、文件、命令。",
].join("\n");

/**
 * The note-writing instruction for projected-slide images.
 *
 * Off by default: downloading a deck and feeding screenshots to a vision
 * model is materially slower and more expensive than a transcript-only note.
 */
function slideImageRule(enabled) {
  return enabled
    ? "讲义插图模式已开启：写讲义前默认抓一次投影（整节课只抓一次），"
      + "从返回的截图里挑 3–8 张关键页（定义、示意图、公式推导、例题），"
      + "按讲义所在目录的相对路径插入 Markdown（例如 ![第 12 页](../ppt-assets/<sub_id>/images/slide-0012.jpg)）；"
      + "如果宿主不能查看本地图片，不要把截图当作已读文字，只在文末列出截图索引。"
      + "用户明确说不要投影时才跳过；不要一次塞入全部截图或图片字节。"
    : "讲义插图模式关闭（默认，节省下载时间与 token）：不要主动下载或插入截图；"
      + "用户明确要求看图时再调用 zju_fetch_slides(download=true)，并在文末列截图索引。";
}

/**
 * The projection-module rule appended to the system prompt.
 *
 * The projection pipeline is opt-in: when it is off, its tools are not even
 * registered, so the prompt must not lead the model into calling them (or
 * reading browser cookies "just in case"). The transcript path never depends
 * on any of this.
 */
function slidesFeatureRule(enableSlides, embedSlideImages) {
  if (!enableSlides) {
    return "PPT 投影抓取已关闭（插件设置 enableSlides=false）：本会话没有注册 zju_fetch_slides，"
      + "不要尝试抓取或引用投影截图，也不要为了投影去读取浏览器 Cookie；"
      + "只用语音字幕与本地课件生成讲义。用户明确要投影画面时，"
      + "告诉他在插件设置里打开「启用 PPT 投影抓取」后重试。";
  }
  return "PPT 投影抓取已开启（插件设置 enableSlides=true）：" + slideImageRule(embedSlideImages);
}

function pdfFeatureRule(enabled) {
  return enabled
    ? "讲义 PDF 自动排版已开启：zju_write_note 会在本地排好同名 PDF 并返回路径；"
      + "排版不需要额外工具、不增加模型 token，PDF 失败也不影响 Markdown。"
      + "返回「找不到 typst」时调用 zju_doctor(install=true) 自动安装后重试。"
      + "返回「PDF 跳过」时先按它点名的公式错误改文件（多半是某条 LaTeX 命令没有 Typst 写法），"
      + "再调用一次 zju_check_note(pdf=true) 重排——这是「不要重复检查」的唯一例外。"
    : "讲义 PDF 自动排版已关闭（插件设置 renderPdf=false）：只交付 Markdown；"
      + "用户要 PDF 时提示他在插件设置里打开「自动排版 PDF 讲义」。";
}

function studyFeatureRule(enabled) {
  return enabled
    ? "填空笔记已开启：写完讲义后默认再出一份填空版（用户只要 Markdown/PDF 或明确说不用时跳过）——"
      + "zju_build_study_notes(mode=draft) 先把讲义搬成底稿：底稿是**纯 Markdown**（公式保持 LaTeX，表格保持 Markdown），"
      + "你只需补 [直觉]/[练习]/[边注] 占位符、正文该挖空的地方写 ____，**不要重写全文**；"
      + "然后 mode=compile 一次性转 Typst 并出 PDF（PDF 会落在底稿同目录）。排版规范交给 scholia-notes Skill。"
    : "填空笔记已关闭（插件设置 enableStudyNotes=false）：本会话没有注册 zju_build_study_notes，"
      + "不要调用或假装调用；用户需要时提示他在插件设置里打开「填空式学习笔记」。";
}

function loginFeatureRule(enabled) {
  return enabled
    ? "登录辅助工具已开启（zju_get_video_url / zju_read_browser_cookie）："
      + "只在确实需要视频直链或预读登录态时使用，二者都不会回显 Cookie。"
    : "登录辅助工具已关闭（enableLoginTools=false）：本会话没有注册 zju_get_video_url / "
      + "zju_read_browser_cookie，不要调用；投影抓取会自行解析登录态，不受影响。";
}

/** Build the (short) task prompt for one configuration. */
function buildSystemPrompt(flags) {
  return [
    SYSTEM_PROMPT,
    slidesFeatureRule(flags.enableSlides, flags.embedSlideImages),
    pdfFeatureRule(flags.renderPdf),
    studyFeatureRule(flags.enableStudyNotes),
    loginFeatureRule(flags.enableLoginTools),
  ].join("\n");
}

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
  zju_fetch_slides: { title: "抓取/下载课堂投影 PPT", kind: "fetch" },
  zju_extract_courseware: { title: "提取本地课件文本", kind: "read" },
  zju_check_note: { title: "检查/修正讲义渲染规范", kind: "edit" },
  zju_write_note: { title: "写入讲义（自动命名 + 写后校验 + PDF）", kind: "edit" },
  zju_get_video_url: { title: "解析回放视频直链", kind: "fetch" },
  zju_read_browser_cookie: { title: "读取本机 Edge 登录态", kind: "read" },
  zju_build_study_notes: { title: "生成填空式学习笔记（Typst → PDF）", kind: "edit" },
  zju_doctor: { title: "检查本机依赖（Typst / 字体 / 包）", kind: "read" },
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
 * Read the bundled skills for in-memory registration.
 *
 * The plugin is installed under a pnpm store path, so the skill files ship
 * inside the package and are read from there; nothing is copied into the user's
 * home directory. The projection appendix is concatenated only when the
 * optional module is enabled.
 *
 * @param {object|boolean} configOrSlides plugin config (or a bare slides flag)
 * @returns {Array<object>} skill descriptors ready for the registry
 */
function readBundledSkills(configOrSlides = {}) {
  const flags = typeof configOrSlides === "boolean"
    ? { ...featureFlags({}), enableSlides: configOrSlides }
    : featureFlags(configOrSlides);
  const skills = [];
  for (const spec of SKILL_SPECS) {
    if (spec.when === "slides" && !flags.enableSlides) continue;
    if (spec.when === "study" && !flags.enableStudyNotes) continue;
    const file = join(skillDir(spec.name), "SKILL.md");
    if (!existsSync(file)) {
      process.stderr.write(`[zju-lecture] 未找到随包 Skill: ${file}\n`);
      continue;
    }
    const raw = readFileSync(file, "utf8");
    const { description, body } = splitFrontmatter(raw);
    let content = body;
    for (const appendix of spec.appendices) {
      if (appendix.when === "slides" && !flags.enableSlides) continue;
      const appendixFile = appendix.path;
      if (!existsSync(appendixFile)) {
        process.stderr.write(`[zju-lecture] 投影抓取已开启，但缺少 Skill 附录: ${appendixFile}\n`);
        continue;
      }
      const text = splitFrontmatter(readFileSync(appendixFile, "utf8")).body.trim();
      if (text) content = `${body.trimEnd()}\n\n---\n\n${text}\n`;
    }
    skills.push({
      name: spec.name,
      description: description || spec.fallbackDescription,
      content,
      path: file,
      source: `plugin:${name}`,
      provider: name,
    });
  }
  return skills;
}

/**
 * 找到 `$DSH_HOME/skills/<name>/SKILL.md` 这类同名的磁盘副本。
 *
 * dsh 的技能注册表对同名 skill 只保留一份（按 rank/层级择优，重复的仅打一条
 * warning，不报错），所以旧版插件"把 Skill 复制进用户目录"或用户手动 `cp -r`
 * 留下的副本，可能把插件内置的那一份静默盖掉：Agent 读到的仍是过期 SOP，
 * 而插件更新看起来"没生效"。这里把它显式报出来。
 *
 * @param {string} skillName bundled skill to look for
 * @returns {string | null} 磁盘副本的路径
 */
function findShadowingSkillCopy(skillName) {
  const roots = [];
  const dshHome = process.env.DSH_HOME?.trim();
  if (dshHome) roots.push(dshHome);
  // dsh 默认把用户级 Skill 放在 ~/.dsh/skills
  if (process.env.USERPROFILE) roots.push(join(process.env.USERPROFILE, ".dsh"));
  if (process.env.HOME) roots.push(join(process.env.HOME, ".dsh"));

  const bundled = join(skillDir(skillName), "SKILL.md");
  for (const root of roots) {
    const candidate = join(root, "skills", skillName, "SKILL.md");
    if (existsSync(candidate) && resolve(candidate) !== resolve(bundled)) return candidate;
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
function warnOnShadowingSkillCopy(flags = featureFlags({})) {
  for (const spec of SKILL_SPECS) {
    if (spec.when === "slides" && !flags.enableSlides) continue;
    if (spec.when === "study" && !flags.enableStudyNotes) continue;
    const shadow = findShadowingSkillCopy(spec.name);
    if (!shadow) continue;
    let stale = true;
    let bundledHash = "?";
    let shadowHash = "?";
    try {
      const bundled = readFileSync(join(skillDir(spec.name), "SKILL.md"));
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
}

function apply(ctx, config = {}) {
  // One normalised feature object drives tools, skills and the prompt. The
  // optional modules default to off, so the verified transcript path never
  // pays for a login/cookie/screenshot/typst dependency it did not ask for.
  const flags = featureFlags(config);
  const timeoutMs = Number(readSetting(config, "timeoutMs")) > 0
    ? Number(readSetting(config, "timeoutMs"))
    : 120000;
  const bridge = new ZjuBridge({
    python: readSetting(config, "python"),
    timeoutMs,
    ...flags,
  });
  ctx.effect(() => () => bridge.dispose());

  if (readSetting(config, "registerSkill") !== false) {
    const skills = readBundledSkills(flags);
    if (skills.length) {
      // Registration is synchronous, so it lands during apply() as the skill
      // registry expects. Disposal is owned by the plugin fiber.
      ctx.inject(["skills"], (ctx) => {
        for (const skill of skills) {
          ctx.skills.register(skill);
        }
      });
      warnOnShadowingSkillCopy(flags);
    } else {
      process.stderr.write("[zju-lecture] 未找到随包 Skill（skills/ 目录为空）\n");
    }
  }

  ctx.inject(["tools"], (ctx) => {
    for (const tool of registerableTools(flags)) {
      const present = TOOL_PRESENT[tool.name] || { title: tool.name, kind: "read" };
      // PDF 链路可能先触发一次 Typst 下载（约 20 MB），所以写讲义 / 补排版与
      // 编译、安装一样给足时间；否则慢网下会把一次正常安装误判成超时。
      const pdfCapable = tool.name === "zju_write_note"
        || tool.name === "zju_check_note"
        || tool.name === "zju_build_study_notes"
        || tool.name === "zju_doctor";
      const toolTimeoutMs = tool.name === "zju_fetch_slides"
        ? Math.max(timeoutMs, SLOW_TOOL_TIMEOUT_MS)
        : pdfCapable
        ? Math.max(timeoutMs, COMPILE_TOOL_TIMEOUT_MS)
        : timeoutMs;
      ctx.tools.register(defineTool({
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters,
        timeoutMs: toolTimeoutMs,
        presentCall: () => ({
          card: "generic",
          title: present.title,
          kind: present.kind,
        }),
        output: jsonOutput,
        execute: async (args, exec) => {
          bridge.useWorkspace(sessionCwd(ctx, exec));
          const text = await bridge.call(tool.name, args ?? {}, { timeoutMs: toolTimeoutMs });
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
        text: buildSystemPrompt(flags),
      });
      return () => {
        if (typeof dispose === "function") dispose();
      };
    });
  });
}

export {
  Config,
  SYSTEM_PROMPT,
  apply,
  buildSystemPrompt,
  featureFlags,
  name,
  readBundledSkills,
  readSetting,
  registerableTools,
  slideImageRule,
  slidesFeatureRule,
  splitFrontmatter,
};
