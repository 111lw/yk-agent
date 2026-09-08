"""MCP 工具基础层：统一结果封装 / 超时 / 错误结构化。

设计规则（docs/07-mcp-tools.md）：工具失败返回结构化 ToolFailure，
绝不抛异常打断编排；由子智能体决定降级策略（见 03 文档护栏）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import pydantic
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT = 10.0  # 单工具超时（秒）


class ToolResult[T: BaseModel](BaseModel):
    """工具统一返回：ok 与 data/error 严格联动，防止"假成功/无原因失败"。"""

    ok: bool
    data: T | None = None
    error: str | None = None

    @pydantic.model_validator(mode="after")
    def _check_invariants(self) -> ToolResult[T]:
        if self.ok and self.data is None:
            raise ValueError("ok=True 时 data 必填")
        if not self.ok and not self.error:
            raise ValueError("ok=False 时 error 必填")
        return self

    @classmethod
    def success(cls, data: T) -> ToolResult[T]:
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, tool: str, error: str) -> ToolResult[T]:
        logger.warning("工具失败 %s: %s", tool, error)
        return cls(ok=False, error=f"{tool}: {error}")


async def run_tool[T: BaseModel](
    tool_name: str,
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    timeout: float = DEFAULT_TOOL_TIMEOUT,
    **kwargs: Any,
) -> ToolResult[T]:
    """执行工具函数：超时或任何异常都收敛为 ToolFailure，不抛穿。"""
    try:
        return ToolResult.success(await asyncio.wait_for(fn(*args, **kwargs), timeout))
    except TimeoutError:
        return ToolResult.failure(tool_name, f"超时（>{timeout}s）")
    except Exception as e:  # noqa: BLE001 — 外部依赖的一切失败都结构化
        return ToolResult.failure(tool_name, f"{type(e).__name__}: {e}")
