/**
 * 插件形态冒烟：用真实的 @deepseek-ai/dsh-* 包执行 apply()。
 *
 * 不启动完整 dsh，而是用一个最小 ctx 模拟 Cordis 的服务注入：
 *   - `tools.register` / `skills.register` / `systemPrompt.section` 都真实调用
 *   - `defineTool` 来自真实的 @deepseek-ai/dsh-tools，会校验参数与输出 schema
 *   - 最后通过桥接真实调用一次 Python 核心
 *
 * 同时验证 v1.5.1 的功能解耦：
 *   - `enableSlides=false`（默认）：只注册字幕主链路的 7 个工具，Skill 不含投影附录；
 *   - `enableSlides=true`：额外注册 zju_fetch_slides，Skill 追加 SLIDES.md 附录。
 *
 * 依赖 `node_modules/@deepseek-ai/*`（开发环境从本机 dsh 安装链接即可）。
 * 缺失时输出 {"ok":true,"skipped":true} 并以 0 退出，方便在无 dsh 的机器上跑测试。
 */

// The plugin imports the dsh peer packages statically, so a missing peer set
// fails while loading the module. Import dynamically to keep this smoke test
// runnable (as a skip) on machines without a dsh installation.
let apply;
try {
  ({ apply } = await import("../lib/index.js"));
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
        return () => {};
      },
    },
    skills: {
      register(skill) {
        state.skills.push(skill);
        return () => {};
      },
    },
    systemPrompt: {
      section(section) {
        state.sections.push(section);
        return () => {};
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
  };
}

const allStates = [];

function runApply(config) {
  const state = { tools: [], skills: [], sections: [], disposers: [] };
  allStates.push(state);
  apply(makeContext(state), config);
  return state;
}

try {
  const core = runApply({ python: "", timeoutMs: 60000, registerSkill: true });
  const full = runApply({
    python: "",
    timeoutMs: 60000,
    registerSkill: true,
    enableSlides: true,
    embedSlideImages: true,
  });

  const names = core.tools.map((tool) => tool.name);
  const namesWithSlides = full.tools.map((tool) => tool.name);
  if (names.length !== 7) throw new Error(`expected 7 core tools, got ${names.length}: ${names}`);
  if (names.includes("zju_fetch_slides")) throw new Error("core mode registered zju_fetch_slides");
  if (namesWithSlides.length !== 8) throw new Error(`expected 8 tools with slides, got ${namesWithSlides.length}`);
  if (!namesWithSlides.includes("zju_fetch_slides")) throw new Error("slides mode did not register zju_fetch_slides");

  for (const tool of [...core.tools, ...full.tools]) {
    if (tool.parameters?.type !== "object") throw new Error(`${tool.name}: parameters not an object schema`);
    if (typeof tool.output?.render !== "function") throw new Error(`${tool.name}: no output renderer`);
    if (typeof tool.execute !== "function") throw new Error(`${tool.name}: no execute`);
  }

  if (core.skills.length !== 1) throw new Error(`expected 1 core skill, got ${core.skills.length}`);
  if (full.skills.length !== 1) throw new Error(`expected 1 full skill, got ${full.skills.length}`);
  const coreSkill = core.skills[0];
  const fullSkill = full.skills[0];
  if (coreSkill.name !== "zju-lecture-summarizer") throw new Error(`unexpected skill name ${coreSkill.name}`);
  if (!coreSkill.content.includes("公式书写规范")) throw new Error("core skill missing the formula spec");
  if (coreSkill.content.includes("## 4. 截图入讲义")) throw new Error("core skill still contains the slides appendix");
  if (coreSkill.content.includes("PPT-<sub_id>.pdf")) throw new Error("core skill still contains slide download rules");
  if (!fullSkill.content.includes("投影抓取模块（可选附录）")) throw new Error("full skill missing the slides appendix");
  if (!fullSkill.content.includes("PPT-<sub_id>.pdf")) throw new Error("full skill missing slide download rules");
  if (!coreSkill.description) throw new Error("skill description is empty");

  if (core.sections.length !== 1 || full.sections.length !== 1) throw new Error("expected one prompt section each");
  if (!core.sections[0].text.includes("隐私边界")) throw new Error("system prompt has no privacy boundary");
  if (!core.sections[0].text.includes("PPT 投影抓取已关闭")) throw new Error("core prompt does not mark slides as off");
  if (core.sections[0].text.includes("讲义插图模式")) throw new Error("core prompt still contains slide-image rules");
  if (!full.sections[0].text.includes("PPT 投影抓取已开启")) throw new Error("full prompt does not mark slides as on");
  if (!full.sections[0].text.includes("讲义插图模式已开启")) throw new Error("full prompt misses the image rule");

  const parseTool = core.tools.find((tool) => tool.name === "zju_parse_url");
  const rendered = parseTool.output.render({}, { text: "hello" });
  if (rendered?.[0]?.text !== "hello") throw new Error("output renderer wraps text in JSON");

  const result = await parseTool.execute({ url: SAMPLE_URL }, { signal: new AbortController().signal });
  if (!result?.text || !result.text.includes("123456")) throw new Error(`unexpected tool result: ${result?.text}`);

  process.stdout.write(`${JSON.stringify({
    ok: true,
    tools: names,
    toolsWithSlides: namesWithSlides,
    skill: coreSkill.name,
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
}
