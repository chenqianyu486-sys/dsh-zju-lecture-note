#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regenerate the OpenAI/DeepSeek function-calling schema from the MCP tool list.

The MCP server owns the single source of truth for tool definitions; the
adapter schema is derived from it so the two cannot drift apart.

Usage:
    python tools/export_schemas.py
"""

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from mcp_server import TOOLS  # noqa: E402

TARGET = os.path.join(REPO_ROOT, "adapters", "deepseek_harness", "tools_schema.json")


def main() -> int:
    schema = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["inputSchema"],
            },
        }
        for tool in TOOLS
    ]
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with open(TARGET, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(schema, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"已生成 {len(schema)} 个工具的 schema: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
