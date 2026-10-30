/**
 * 端到端冒烟：拉起 Python 核心，真实调用一次 zju_parse_url。
 *
 * 用法：node tests/bridge_smoke.mjs
 * 输出：一行 JSON，形如 {"ok":true,"result":"..."}
 *
 * 这里只使用虚构的课程/回放编号，仓库里不出现任何真实课程标识。
 */

import { ZjuBridge } from "../lib/bridge.js";
import { ZJU_TOOLS } from "../lib/tools.js";

const SAMPLE_URL = "https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456&tenant_code=112";

const bridge = new ZjuBridge({ timeoutMs: 60000 });
try {
  const result = await bridge.call("zju_parse_url", { url: SAMPLE_URL });
  process.stdout.write(`${JSON.stringify({ ok: true, tools: ZJU_TOOLS.length, result })}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: String(error?.message ?? error) })}\n`);
  process.exitCode = 1;
} finally {
  bridge.dispose();
}
