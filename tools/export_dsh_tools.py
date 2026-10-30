#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Python 核心的 TOOLS 生成 dsh 工具定义。

dsh 的 `defineTool` 期望 `parameters` 是「属性名 -> 属性 schema」的映射，
必填项用属性内的 `required: true` 表达；MCP 的 inputSchema 用顶层
`required` 数组表达。两者在这里转换。

dsh 还会在注册时校验 schema 的**有限子集**：`minimum`/`maximum`/`pattern`
这类关键字会被直接拒绝（插件启动即失败），因此这里只保留 defineTool
支持的注解与结构键；MCP schema 仍保留完整约束，不受影响。

用法：
    python tools/export_dsh_tools.py

产出：
    lib/tools.js          dsh 工具定义（ESM）
    lib/tools.schema.json 同一份数据的 JSON 快照，供测试比对
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mcp_server import TOOLS  # noqa: E402

# dsh's defineTool compiles a narrow author schema; keywords such as
# `minimum`/`maximum`/`pattern` are rejected at registration time. The MCP
# schema keeps them (MCP hosts understand full JSON Schema), so the dsh
# projection is filtered to the supported subset.
DSH_ANNOTATION_KEYS = ("description", "title", "default", "examples")
DSH_VALUE_KEYS = ("type", "enum", "const", "oneOf", "items", "properties", "additionalProperties")


def to_dsh_schema(schema):
    """Project one JSON Schema value node onto the dsh author schema DSL."""
    if not isinstance(schema, dict):
        return schema
    converted = {}
    for key in DSH_ANNOTATION_KEYS + DSH_VALUE_KEYS:
        if key not in schema:
            continue
        value = schema[key]
        if key == "properties" and isinstance(value, dict):
            converted[key] = {name: to_dsh_schema(child) for name, child in value.items()}
        elif key == "items":
            converted[key] = to_dsh_schema(value)
        elif key == "oneOf" and isinstance(value, list):
            converted[key] = [to_dsh_schema(child) for child in value]
        else:
            converted[key] = value
    return converted


def to_dsh_parameters(input_schema):
    """MCP inputSchema -> dsh parameters."""
    required = set(input_schema.get("required") or [])
    parameters = {}
    for name, schema in (input_schema.get("properties") or {}).items():
        entry = to_dsh_schema(schema)
        if name in required:
            entry["required"] = True
        parameters[name] = entry
    return parameters


def build_tools():
    tools = []
    for tool in TOOLS:
        tools.append({
            "name": tool["name"],
            "description": tool["description"],
            "parameters": to_dsh_parameters(tool["inputSchema"]),
        })
    return tools


HEADER = """// 本文件由 tools/export_dsh_tools.py 自动生成，请勿手工编辑。
// 数据源：mcp_server.py 的 TOOLS。

export const ZJU_TOOLS = """


def main() -> int:
    tools = build_tools()

    js_path = os.path.join(ROOT, "lib", "tools.js")
    body = json.dumps(tools, ensure_ascii=False, indent=2)
    with open(js_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(HEADER + body + ";\n")

    schema_path = os.path.join(ROOT, "lib", "tools.schema.json")
    with open(schema_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(tools, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"已生成 {len(tools)} 个 dsh 工具定义:")
    for tool in tools:
        print(f"  - {tool['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
