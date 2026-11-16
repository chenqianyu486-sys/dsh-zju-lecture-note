import assert from "node:assert/strict";
import { splitFrontmatter } from "../lib/index.js";

for (const newline of ["\n", "\r\n"]) {
  const raw = ["---", "name: sample", "description: 示例说明", "---", "", "正文", ""].join(newline);
  const parsed = splitFrontmatter(raw);
  assert.equal(parsed.description, "示例说明");
  assert.equal(parsed.body, "正文\n");
}
console.log(JSON.stringify({ ok: true, lineEndings: ["LF", "CRLF"] }));
