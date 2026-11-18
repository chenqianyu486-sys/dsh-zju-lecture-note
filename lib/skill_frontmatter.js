/**
 * Split YAML frontmatter from a SKILL.md file.
 *
 * Git may check text files out with CRLF on Windows (core.autocrlf=true).
 * Frontmatter is structural YAML, not user-visible text, so normalize line
 * endings before parsing. The returned body is normalized to LF as well; that
 * keeps in-memory Skill registration deterministic across platforms.
 *
 * @param {string} raw
 * @returns {{description: string, body: string}}
 */
export function splitFrontmatter(raw) {
  const text = String(raw).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  if (!text.startsWith("---\n")) return { description: "", body: text };
  const end = text.indexOf("\n---", 4);
  if (end === -1) return { description: "", body: text };
  const front = text.slice(4, end);
  const body = text.slice(end + 4).replace(/^\s*\n/, "");
  const lines = front.split("\n");
  let description = "";
  for (let index = 0; index < lines.length; index += 1) {
    const match = /^description:\s*(.*)$/.exec(lines[index]);
    if (!match) continue;
    const value = match[1].trim();
    if (!["|", ">", "|-", ">-"].includes(value)) {
      description = value;
      break;
    }
    // Minimal YAML block-scalar support: the shipped scholia Skill uses
    // `description: |` with indented continuation lines.
    const block = [];
    for (let next = index + 1; next < lines.length; next += 1) {
      const line = lines[next];
      if (line && !/^\s/.test(line)) break;
      if (line.trim()) block.push(line.trim());
    }
    description = block.join(value.startsWith(">") ? " " : "\n");
    break;
  }
  return { description, body };
}
