#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Example Agent Harness for DeepSeek / OpenAI models with ZJU Lecture Tools.
Shows how to equip an LLM loop with ZJU lecture tools.
"""

import json
import os
import sys
import urllib.request

# Add parent path to import zju_lecture
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(CURRENT_DIR)
if PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, PLUGIN_ROOT)

from mcp_server import TOOLS, handle_tool_call


def run_agent_turn(api_key: str, user_prompt: str, base_url: str = "https://api.deepseek.com"):
    """Demonstrates a simple 1-turn ReAct / Function Calling loop."""
    system_prompt_file = os.path.join(CURRENT_DIR, "system_prompt.txt")
    with open(system_prompt_file, "r", encoding="utf-8") as f:
        system_content = f.read()

    # Convert MCP TOOLS to OpenAI function schema
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"]
            }
        }
        for t in TOOLS
    ]

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_prompt}
    ]

    print(f"[Agent] Sending user prompt to {base_url}...")
    req_body = {
        "model": "deepseek-chat",
        "messages": messages,
        "tools": openai_tools,
        "tool_choice": "auto"
    }

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(req_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )

    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))

    msg = res["choices"][0]["message"]
    tool_calls = msg.get("tool_calls", [])

    if not tool_calls:
        print("[Agent Response]:\n", msg.get("content"))
        return

    # Execute tools
    messages.append(msg)
    for tc in tool_calls:
        call_id = tc["id"]
        func_name = tc["function"]["name"]
        func_args = json.loads(tc["function"]["arguments"])
        print(f"[Harness] Executing tool: {func_name} with args: {func_args}")
        tool_output = handle_tool_call(func_name, func_args)

        messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": func_name,
            "content": str(tool_output)[:100000]  # ensure within context limit
        })

    # Second pass: let model generate final summary
    print("[Agent] Generating final lecture summary...")
    req_body_final = {
        "model": "deepseek-chat",
        "messages": messages,
        "max_tokens": 8192
    }
    req2 = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(req_body_final).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )
    with urllib.request.urlopen(req2) as resp:
        final_res = json.loads(resp.read().decode("utf-8"))

    final_text = final_res["choices"][0]["message"]["content"]
    print("\n========== 最终课程讲义 ==========\n")
    print(final_text)


if __name__ == "__main__":
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("提示: 设置 DEEPSEEK_API_KEY 环境变量后运行该测试脚本。")
        print("用法: DEEPSEEK_API_KEY=sk-... python3 example_harness.py")
        sys.exit(0)

    url_example = "https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456&tenant_code=112"
    run_agent_turn(key, f"请帮我整理这节课的知识讲义: {url_example}")
