# Claude Code 接入指南

本指南说明如何在 Anthropic 的 **Claude Code** (CLI) 中接入浙大智云课堂 Agent 工具。

> 插件仓库同时提供 Claude Code 插件清单
> [`plugin.json`](plugin.json)，可直接作为 Claude Code 插件目录使用。

---

## 方式一：使用 `claude mcp add` 命令（推荐）

在终端中执行（将 `/path/to/zju-lecture-agent-plugin` 替换为实际绝对路径）：

```bash
claude mcp add zju-lecture node /path/to/zju-lecture-agent-plugin/server.mjs
```

或者使用项目内安装：

```bash
claude mcp add --scope project zju-lecture node /path/to/zju-lecture-agent-plugin/server.mjs
```

> 为什么是 `node` 而不是 `python3`：`server.mjs` 会在运行时解析 Python 解释器
> （依次尝试 `python3` / `python` / `py -3`，要求 3.9+），
> 因此同一份配置在 macOS、Linux 与 Windows 上都成立。

---

## 方式二：手动配置 `~/.claude.json` 或项目内 `.claude/mcp.json`

```json
{
  "mcpServers": {
    "zju-lecture": {
      "type": "stdio",
      "command": "node",
      "args": ["/绝对路径/zju-lecture-agent-plugin/server.mjs"],
      "timeout": 120000
    }
  }
}
```

---

## 配合 Skill 使用

将 `skills/zju-lecture-summarizer/SKILL.md` 的内容添加到工作区的 `CLAUDE.md`
或 `.claude/skills/zju-lecture-summarizer.md` 中。

随后，在 Claude Code 会话中只需直接输入指令即可：

```bash
claude "帮我整理这节课的笔记：https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456&tenant_code=112"
```

Claude Code 将自动调用 MCP 工具抓取字幕、解析内容，并按格式输出 `知识总结.md`。
