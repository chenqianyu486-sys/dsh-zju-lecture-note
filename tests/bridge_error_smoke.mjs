/**
 * 端到端冒烟：MCP 的 `isError: true` 必须变成 JS 异常。
 *
 * 以前桥接先取 `content[0].text`、后判 `isError`，等于把工具失败当成功交给宿主：
 * UI 上是绿的，模型只能从正文里猜"这行字是不是报错"，也就触发不了降级与重试。
 *
 * 用法：node tests/bridge_error_smoke.mjs
 * 输出：一行 JSON，形如 {"ok":true,"message":"..."}
 *
 * 这里用一个非法 sub_id 触发服务端的错误分支，不联网、结果确定。
 */

import { ZjuBridge } from "../lib/bridge.js";

const bridge = new ZjuBridge({ timeoutMs: 60000 });
const payload = { ok: false, message: "" };
try {
  await bridge.call("zju_fetch_transcript", { url_or_sub_id: "not-a-sub-id" });
  payload.message = "调用没有抛错——isError 又被当成了正常结果";
} catch (error) {
  payload.ok = true;
  payload.message = String(error?.message ?? error);
} finally {
  bridge.dispose();
}

process.stdout.write(`${JSON.stringify(payload)}\n`);
process.exitCode = payload.ok ? 0 : 1;
