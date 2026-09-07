"""外部工具的 MCP 封装：map / weather(V2)。工具契约见 docs/07-mcp-tools.md。

规则：先登记契约（pydantic）再实现；独立超时；错误结构化返回不抛异常打断编排。
"""
