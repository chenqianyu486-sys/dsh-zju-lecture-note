/**
 * 插件形态冒烟：用真实的 @deepseek-ai/dsh-* 包执行 apply()。
 *
 * 不启动完整 dsh，而是用一个最小 ctx 模拟 Cordis 的服务注入：
 *   - `tools.register` / `skills.register` / `systemPrompt.section` 都真实调用
 *   - `defineTool` 来自真实的 @deepseek-ai/dsh-tools，会校验参数与输出 schema
 *   - 最后通过桥接真实调用一次 Python 核心
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

const state = { tools: [], skills: [], sections: [], disposers: [] };

const ctx = {
  effect(callback) {
    const dispose = callback();
    if (typeof dispose === "function") state.disposers.push(dispose);
    return dispose;
  },
  inject(services, callback) {
    callback(makeScopedContext(state));
  },
};

try {
  apply(ctx, { python: "", timeoutMs: 60000, registerSkill: true });

  const names = state.tools.map((tool) => tool.name);
  if (names.length !== 8) throw new Error(`expected 8 tools, got ${names.length}`);

  for (const tool of state.tools) {
    if (tool.parameters?.type !== "object") throw new Error(`${tool.name}: parameters not an object schema`);
    if (typeof tool.output?.render !== "function") throw new Error(`${tool.name}: no output renderer`);
    if (typeof tool.execute !== "function") throw new Error(`${tool.name}: no execute`);
  }

  if (state.skills.length !== 1) throw new Error(`expected 1 skill, got ${state.skills.length}`);
  const skill = state.skills[0];
  if (skill.name !== "zju-lecture-summarizer") throw new Error(`unexpected skill name ${skill.name}`);
  if (!skill.content.includes("公式书写规范")) throw new Error("skill body missing the formula spec");
  if (!skill.description) throw new Error("skill description is empty");

  if (state.sections.length !== 1) throw new Error(`expected 1 prompt section, got ${state.sections.length}`);
  if (!state.sections[0].text.includes("隐私边界")) throw new Error("system prompt has no privacy boundary");

  const parseTool = state.tools.find((tool) => tool.name === "zju_parse_url");
  const rendered = parseTool.output.render({}, { text: "hello" });
  if (rendered?.[0]?.text !== "hello") throw new Error("output renderer wraps text in JSON");

  const result = await parseTool.execute({ url: SAMPLE_URL }, { signal: new AbortController().signal });
  if (!result?.text || !result.text.includes("123456")) throw new Error(`unexpected tool result: ${result?.text}`);

  process.stdout.write(`${JSON.stringify({
    ok: true,
    tools: names,
    skill: skill.name,
    section: state.sections[0].name,
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
  for (const dispose of state.disposers.splice(0).reverse()) {
    try {
      dispose();
    } catch {
      /* ignore */
    }
  }
}
