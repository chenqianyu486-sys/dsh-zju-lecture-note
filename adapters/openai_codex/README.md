# OpenAI Codex / GPT-4o / Agent Swarm 接入指南

本指南指导如何将 ZJU Lecture Summarizer 工具集接入基于 OpenAI 规范的 Agent 框架（如 OpenAI Assistants API, Codex, LangChain, LlamaIndex, AutoGen 等）。

---

## 1. 挂载 Function Tools

将 `adapters/deepseek_harness/tools_schema.json` 中的函数列表直接导入到 Assistant 的 `tools` 字段中：

```python
import json
from openai import OpenAI
from mcp_server import handle_tool_call

client = OpenAI()

with open("adapters/deepseek_harness/tools_schema.json") as f:
    tools = json.load(f)

assistant = client.beta.assistants.create(
    name="ZJU Course Tutor",
    instructions=open("adapters/openai_codex/assistant_instructions.md").read(),
    tools=tools,
    model="gpt-4o"
)
```

---

## 2. 工具分发调度

当模型返回 `tool_calls` 时，直接路由至 `handle_tool_call`：

```python
for tool_call in run.required_action.submit_tool_outputs.tool_calls:
    func_name = tool_call.function.name
    arguments = json.loads(tool_call.function.arguments)
    output = handle_tool_call(func_name, arguments)
    tool_outputs.append({
        "tool_call_id": tool_call.id,
        "output": str(output)
    })
```
