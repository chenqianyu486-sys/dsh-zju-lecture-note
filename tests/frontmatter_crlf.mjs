import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { splitFrontmatter } from "../lib/skill_frontmatter.js";

const results = [];
for (const eol of ["\n", "\r\n"]) {
  const raw = [
    "---",
    "name: demo-skill",
    "description: line ending independent",
    "---",
    "",
    "# Body",
    "",
  ].join(eol);
  const parsed = splitFrontmatter(raw);
  assert.equal(parsed.description, "line ending independent");
  assert.equal(parsed.body, "# Body\n");
  results.push(eol === "\n" ? "lf" : "crlf");
}

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const realSkills = [
  "zju-lecture-summarizer",
  "zju-lecture-summarizer-help",
  "zju-lecture-summarizer-login",
  "scholia-notes",
];
for (const name of realSkills) {
  const raw = readFileSync(join(root, "skills", name, "SKILL.md"), "utf8");
  const parsed = splitFrontmatter(raw);
  assert.ok(parsed.description.length > 0, `${name}: description missing`);
  assert.notEqual(parsed.description, "|", `${name}: block scalar was not parsed`);
  assert.ok(!parsed.body.startsWith("---"), `${name}: frontmatter leaked into body`);
}

process.stdout.write(`${JSON.stringify({ ok: true, parsed: results, realSkills })}\n`);
