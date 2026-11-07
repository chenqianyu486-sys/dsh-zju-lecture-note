/**
 * 插件形态冒烟：用真实的 @deepseek-ai/dsh-* 包执行 apply()。
 *
 * 不启动完整 dsh，而是用一个最小 ctx 模拟 Cordis 的服务注入：
 *   - `tools.register` / `skills.register` / `systemPrompt.section` 都真实调用
 *   - `defineTool` 来自真实的 @deepseek-ai/dsh-tools，会校验参数与输出 schema
 *   - 最后通过桥接真实调用一次 Python 核心
 *
 * 同时验证 v2.0.1 的功能解耦：
 *   - 默认配置：字幕核心 7 个工具（含一键登录）+ 自动 PDF，可选模块全部不注册；
 *   - 打开填空笔记：额外注册 zju_build_study_notes，并加载 scholia-notes Skill；
 *   - 打开投影/登录辅助：额外注册对应工具，Skill 追加 SLIDES.md 附录。
 *
 * 随包分发四个 Skill（zju-lecture-summarizer / zju-lecture-summarizer-help /
 * zju-lecture-summarizer-login / scholia-notes）；help 与 login 只面向用户命令、不进入
 * 模型目录，scholia-notes 只在 enableStudyNotes 打开时注册。
 *
 * 依赖 `node_modules/@deepseek-ai/*`（开发环境从本机 dsh 安装链接即可）。
 * 缺失时输出 {"ok":true,"skipped":true} 并以 0 退出，方便在无 dsh 的机器上跑测试。
 */

// The plugin imports the dsh peer packages statically, so a missing peer set
// fails while loading the module. Import dynamically to keep this smoke test
// runnable (as a skip) on machines without a dsh installation.
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

let apply;
let bridgeOptions;
let featureFlags;
let readSetting;
try {
  ({ apply, bridgeOptions, featureFlags, readSetting } = await import("../lib/index.js"));
} catch (error) {
  const message = String(error?.message ?? error);
  if (/Cannot find package '@deepseek-ai\//.test(message)) {
    process.stdout.write(`${JSON.stringify({ ok: true, skipped: true, reason: message })}\n`);
    process.exit(0);
  }
  throw error;
}

const SAMPLE_URL = "https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456&tenant_code=112";

function makeScopedContext(state) {
  return {
    tools: {
      register(definition) {
        state.tools.push(definition);
        return () => {
          const index = state.tools.indexOf(definition);
          if (index >= 0) state.tools.splice(index, 1);
        };
      },
    },
    skills: {
      register(skill) {
        state.skills.push(skill);
        return () => {
          const index = state.skills.indexOf(skill);
          if (index >= 0) state.skills.splice(index, 1);
        };
      },
    },
    systemPrompt: {
      section(section) {
        state.sections.push(section);
        return () => {
          const index = state.sections.indexOf(section);
          if (index >= 0) state.sections.splice(index, 1);
        };
      },
    },
    effect(callback) {
      const dispose = callback();
      if (typeof dispose === "function") state.disposers.push(dispose);
      return dispose;
    },
  };
}

function makeContext(state) {
  return {
    effect(callback) {
      const dispose = callback();
      if (typeof dispose === "function") state.disposers.push(dispose);
      return dispose;
    },
    inject(services, callback) {
      callback(makeScopedContext(state));
    },
    on(name, listener) {
      const bucket = state.listeners[name] ?? [];
      bucket.push(listener);
      state.listeners[name] = bucket;
      return () => {
        const index = bucket.indexOf(listener);
        if (index >= 0) bucket.splice(index, 1);
      };
    },
  };
}

const allStates = [];
// A real dsh tool call always carries the session; the bridge refuses to run
// without a workspace (it must never fall back to the plugin directory).
const sessionWorkspace = mkdtempSync(join(tmpdir(), "zju-plugin-apply-"));

function runApply(config) {
  const state = { tools: [], skills: [], sections: [], disposers: [], listeners: {} };
  state.context = makeContext(state);
  state.emit = (name, payload) => {
    for (const listener of [...(state.listeners[name] ?? [])]) listener(payload);
  };
  allStates.push(state);
  apply(state.context, config);
  return state;
}

/** The system prompt is a thunk so every assembly re-reads the live config. */
function sectionText(state) {
  const section = state.sections[0];
  if (!section) throw new Error("no system prompt section registered");
  return typeof section.text === "function" ? section.text({}) : section.text;
}

try {
  const core = runApply({ python: "", timeoutMs: 60000, registerSkill: true });
  const study = runApply({
    python: "",
    timeoutMs: 60000,
    registerSkill: true,
    enableStudyNotes: true,
  });
  const full = runApply({
    python: "",
    timeoutMs: 60000,
    registerSkill: true,
    enableSlides: true,
    embedSlideImages: true,
    enableStudyNotes: true,
    enableLoginTools: true,
  });
  // dsh projects `.volatile()` Config fields as live `{ get() }` references,
  // not primitives. A plugin that compares the reference to `true` always
  // sees "off", so this shape must be covered explicitly.
  const ref = (value) => ({ get: () => value });
  const liveRef = (initial) => {
    const box = { value: initial };
    return {
      get: () => box.value,
      set: (next) => {
        box.value = next;
      },
    };
  };
  const liveRefs = {
    python: liveRef(""),
    timeoutMs: liveRef(60000),
    registerSkill: liveRef(true),
    renderPdf: liveRef(true),
    enableSlides: liveRef(true),
    embedSlideImages: liveRef(true),
    enableStudyNotes: liveRef(true),
    enableLoginTools: liveRef(true),
    typstAutoInstall: liveRef(true),
    typstPath: liveRef(""),
    typstMirror: liveRef(""),
  };
  const live = runApply(liveRefs);

  const projected = bridgeOptions({
    python: ref("C:\\Python\\python.exe"),
    timeoutMs: ref(90000),
    typstPath: ref("C:\\typst\\typst.exe"),
    typstMirror: ref("https://ghfast.top/"),
    enableSlides: ref(true),
    renderPdf: ref(false),
  });
  if (projected.python !== "C:\\Python\\python.exe" || projected.timeoutMs !== 90000) {
    throw new Error(`bridgeOptions did not unwrap live refs: ${JSON.stringify(projected)}`);
  }
  if (projected.typstPath !== "C:\\typst\\typst.exe" || projected.typstMirror !== "https://ghfast.top/") {
    throw new Error(`bridgeOptions dropped the Typst path/mirror: ${JSON.stringify(projected)}`);
  }
  if (projected.enableSlides !== true || projected.renderPdf !== false) {
    throw new Error(`bridgeOptions mixed up the feature flags: ${JSON.stringify(projected)}`);
  }

  const flags = featureFlags({
    renderPdf: ref(true),
    enableSlides: ref(true),
    embedSlideImages: ref(true),
    enableStudyNotes: ref(true),
    enableLoginTools: ref(true),
    typstAutoInstall: ref(false),
  });
  if (flags.enableSlides !== true || flags.enableStudyNotes !== true || flags.enableLoginTools !== true) {
    throw new Error(`volatile config refs were not unwrapped: ${JSON.stringify(flags)}`);
  }
  if (flags.typstAutoInstall !== false || flags.renderPdf !== true) {
    throw new Error(`volatile config defaults are wrong: ${JSON.stringify(flags)}`);
  }
  if (readSetting({ enableSlides: ref(true) }, "enableSlides") !== true) {
    throw new Error("readSetting did not unwrap a config reference");
  }

  const names = core.tools.map((tool) => tool.name);
  const namesWithStudy = study.tools.map((tool) => tool.name);
  const namesFull = full.tools.map((tool) => tool.name);
  const namesLive = live.tools.map((tool) => tool.name);
  if (names.length !== 7) throw new Error(`expected 7 core tools, got ${names.length}: ${names}`);
  if (!names.includes("zju_login")) throw new Error("core mode is missing zju_login");
  for (const optional of ["zju_fetch_slides", "zju_build_study_notes", "zju_get_video_url", "zju_read_browser_cookie"]) {
    if (names.includes(optional)) throw new Error(`core mode registered optional tool ${optional}`);
  }
  if (namesWithStudy.length !== 8 || !namesWithStudy.includes("zju_build_study_notes")) {
    throw new Error(`study mode tools are wrong: ${namesWithStudy}`);
  }
  if (namesFull.length !== 11) throw new Error(`expected 11 tools with every module, got ${namesFull.length}`);
  if (namesLive.length !== 11) throw new Error(`volatile refs registered ${namesLive.length} tools, expected 11`);
  for (const optional of ["zju_fetch_slides", "zju_build_study_notes", "zju_get_video_url", "zju_read_browser_cookie"]) {
    if (!namesFull.includes(optional)) throw new Error(`full mode missing ${optional}`);
    if (!namesLive.includes(optional)) throw new Error(`volatile refs missing ${optional}`);
  }

  for (const tool of [...core.tools, ...study.tools, ...full.tools]) {
    if (tool.parameters?.type !== "object") throw new Error(`${tool.name}: parameters not an object schema`);
    if (typeof tool.output?.render !== "function") throw new Error(`${tool.name}: no output renderer`);
    if (typeof tool.execute !== "function") throw new Error(`${tool.name}: no execute`);
  }

  if (core.skills.length !== 3) throw new Error(`expected 3 core skills, got ${core.skills.length}`);
  if (study.skills.length !== 4) throw new Error(`expected 4 skills with study mode, got ${study.skills.length}`);
  if (full.skills.length !== 4) throw new Error(`expected 4 full skills, got ${full.skills.length}`);
  const coreSkill = core.skills[0];
  const helpSkill = core.skills[1];
  const loginSkill = core.skills[2];
  const studySkill = study.skills[3];
  const fullSkill = full.skills[0];
  if (coreSkill.name !== "zju-lecture-summarizer") throw new Error(`unexpected skill name ${coreSkill.name}`);
  if (helpSkill.name !== "zju-lecture-summarizer-help") throw new Error(`unexpected help skill name ${helpSkill.name}`);
  if (!helpSkill.content.includes("隐私红线")) throw new Error("help skill missing the privacy guardrails");
  if (!helpSkill.content.includes("zju_doctor(login=true)")) throw new Error("help skill does not mention the opt-in login check");
  if (!helpSkill.description) throw new Error("help skill description is empty");
  if (helpSkill.invocation?.modelInvocable !== false || helpSkill.invocation?.userInvocable !== true) {
    throw new Error(`help skill must be user-only: ${JSON.stringify(helpSkill.invocation)}`);
  }
  if (loginSkill.name !== "zju-lecture-summarizer-login") throw new Error(`unexpected login skill name ${loginSkill.name}`);
  if (!loginSkill.content.includes("zju_login")) throw new Error("login skill does not mention zju_login");
  if (loginSkill.invocation?.modelInvocable !== false || loginSkill.invocation?.userInvocable !== true) {
    throw new Error(`login skill must be user-only: ${JSON.stringify(loginSkill.invocation)}`);
  }
  if (studySkill.name !== "scholia-notes") throw new Error(`unexpected second skill name ${studySkill.name}`);
  if (!studySkill.content.includes("zju_build_study_notes")) throw new Error("scholia-notes skill does not mention the study-notes tool");
  if (!studySkill.description) throw new Error("scholia-notes description is empty");
  if (!coreSkill.content.includes("公式书写规范")) throw new Error("core skill missing the formula spec");
  if (coreSkill.content.includes("## 4. 截图入讲义")) throw new Error("core skill still contains the slides appendix");
  if (coreSkill.content.includes("PPT-<sub_id>.pdf")) throw new Error("core skill still contains slide download rules");
  if (coreSkill.content.includes("先调用 `zju_parse_url`")) throw new Error("core skill still tells the agent to parse the URL first");
  if (!fullSkill.content.includes("投影抓取模块（可选附录）")) throw new Error("full skill missing the slides appendix");
  if (!fullSkill.content.includes("PPT-<sub_id>.pdf")) throw new Error("full skill missing slide download rules");
  if (!coreSkill.description) throw new Error("skill description is empty");

  if (core.sections.length !== 1 || study.sections.length !== 1 || full.sections.length !== 1) {
    throw new Error("expected one prompt section each");
  }
  const coreText = sectionText(core);
  const studyText = sectionText(study);
  const fullText = sectionText(full);
  const liveText = sectionText(live);
  if (!coreText.includes("隐私边界")) throw new Error("system prompt has no privacy boundary");
  if (!coreText.includes("PPT 投影抓取已关闭")) throw new Error("core prompt does not mark slides as off");
  if (coreText.includes("讲义插图模式")) throw new Error("core prompt still contains slide-image rules");
  if (!coreText.includes("PDF 自动排版已开启")) throw new Error("core prompt misses the PDF rule");
  if (!coreText.includes("填空笔记已关闭")) throw new Error("core prompt misses the study-notes gate");
  if (!studyText.includes("填空笔记已开启")) throw new Error("study prompt does not mark study notes on");
  if (!fullText.includes("PPT 投影抓取已开启")) throw new Error("full prompt does not mark slides as on");
  if (!fullText.includes("讲义插图模式已开启")) throw new Error("full prompt misses the image rule");
  if (!fullText.includes("登录辅助工具已开启")) throw new Error("full prompt misses the login rule");
  if (!liveText.includes("PPT 投影抓取已开启")) throw new Error("volatile refs did not reach the prompt (slides)");
  if (!liveText.includes("填空笔记已开启")) throw new Error("volatile refs did not reach the prompt (study notes)");
  if (!liveText.includes("登录辅助工具已开启")) throw new Error("volatile refs did not reach the prompt (login tools)");
  if (!coreText.includes("复习版")) throw new Error("core prompt misses the review-note contract");
  if (!coreText.includes("例题")) throw new Error("core prompt misses the worked-example rule");
  if (!coreText.includes("自测题")) throw new Error("core prompt misses the self-test rule");
  if (flags.registerSkill !== true) throw new Error("registerSkill default should be on");

  // A volatile-only save does not re-run apply(); the plugin must reconcile
  // tools, Skills and the prompt from `loader/volatile-update` itself.
  liveRefs.enableSlides.set(false);
  liveRefs.enableStudyNotes.set(false);
  liveRefs.enableLoginTools.set(false);
  liveRefs.embedSlideImages.set(false);
  live.emit("loader/volatile-update", [["enableSlides"], ["enableStudyNotes"], ["enableLoginTools"]]);
  if (live.tools.length !== 7) {
    throw new Error(`live disable left ${live.tools.length} tools, expected 7`);
  }
  if (live.skills.length !== 3) {
    throw new Error(`live disable left ${live.skills.length} skills, expected 3`);
  }
  if (!sectionText(live).includes("PPT 投影抓取已关闭")) {
    throw new Error("live prompt did not follow the disabled slides switch");
  }

  liveRefs.enableSlides.set(true);
  liveRefs.enableStudyNotes.set(true);
  live.emit("loader/volatile-update", [["enableSlides"], ["enableStudyNotes"]]);
  if (live.tools.length !== 9) {
    throw new Error(`live enable registered ${live.tools.length} tools, expected 9`);
  }
  if (live.skills.length !== 4) {
    throw new Error(`live study switch did not add scholia-notes: ${live.skills.length}`);
  }
  if (!sectionText(live).includes("PPT 投影抓取已开启")) {
    throw new Error("live prompt did not follow the enabled slides switch");
  }

  liveRefs.registerSkill.set(false);
  live.emit("loader/volatile-update", [["registerSkill"]]);
  if (live.skills.length !== 0) {
    throw new Error(`registerSkill=false left ${live.skills.length} skills registered`);
  }
  if (!sectionText(live).includes("随包 Skill 未注册")) {
    throw new Error("live prompt did not explain the disabled Skills");
  }
  if (!sectionText(live).includes("通用数学规范")) {
    throw new Error("live prompt still points at a Skill that is not registered");
  }

  liveRefs.registerSkill.set(true);
  liveRefs.timeoutMs.set(1500);
  live.emit("loader/volatile-update", [["registerSkill"], ["timeoutMs"]]);
  if (live.skills.length !== 4) {
    throw new Error(`re-enabled Skills registered ${live.skills.length}, expected 4`);
  }
  const liveParse = live.tools.find((tool) => tool.name === "zju_parse_url");
  if (liveParse?.timeoutMs !== 1500) {
    throw new Error(`live timeout edit did not re-register the tool: ${liveParse?.timeoutMs}`);
  }

  const parseTool = core.tools.find((tool) => tool.name === "zju_parse_url");
  const rendered = parseTool.output.render({}, { text: "hello" });
  if (rendered?.[0]?.text !== "hello") throw new Error("output renderer wraps text in JSON");

  const result = await parseTool.execute(
    { url: SAMPLE_URL },
    {
      signal: new AbortController().signal,
      agent: { session: { header: { cwd: sessionWorkspace } } },
    },
  );
  if (!result?.text || !result.text.includes("123456")) throw new Error(`unexpected tool result: ${result?.text}`);

  process.stdout.write(`${JSON.stringify({
    ok: true,
    tools: names,
    toolsWithStudy: namesWithStudy,
    toolsWithSlides: namesFull,
    toolsFull: namesFull,
    skill: coreSkill.name,
    skills: core.skills.map((item) => item.name),
    skillsWithStudy: study.skills.map((item) => item.name),
    helpInvocation: helpSkill.invocation,
    loginInvocation: loginSkill.invocation,
    skillHasSlides: fullSkill.content.includes("投影抓取模块（可选附录）"),
    section: core.sections[0].name,
    result: result.text.trim().replace(/\s+/g, " "),
  })}\n`);
} catch (error) {
  const message = String(error?.message ?? error);
  if (/Cannot find package '@deepseek-ai\//.test(message)) {
    process.stdout.write(`${JSON.stringify({ ok: true, skipped: true, reason: message })}\n`);
  } else {
    process.stdout.write(`${JSON.stringify({ ok: false, error: message })}\n`);
    process.exitCode = 1;
  }
} finally {
  for (const state of allStates) {
    for (const dispose of state.disposers.splice(0).reverse()) {
      try {
        dispose();
      } catch {
        /* ignore */
      }
    }
  }
  try {
    rmSync(sessionWorkspace, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
  } catch {
    /* Windows 会稍后回收 %TEMP% */
  }
}
