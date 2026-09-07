"""Agent Registry：子智能体注册表——自主编排的前提。

硬规则（CLAUDE.md / docs/03-agent-orchestration.md）：
- 所有子智能体必须经 Registry 注册，业务代码禁止硬编码调用某个子智能体；
- description 是给 LLM 看的能力描述，质量直接决定编排质量，
  必须写清【能做什么/输入是什么/输出是什么/什么场景该选它】。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

# 子智能体执行体：入参为派发载荷（已通过 input_schema 校验），出参须符合 output_schema
AgentRunnable = Callable[[dict], Awaitable[dict]]


@dataclass(frozen=True)
class AgentSpec:
    name: str  # 全局唯一，kebab-case，如 "poi-agent"
    description: str  # 给 LLM 看的能力描述
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    graph_node: str  # LangGraph 节点名，默认与 name 相同
    side_effect: bool = False  # True → 派发前必须人工确认（硬规则）

    def __post_init__(self) -> None:
        if self.side_effect:
            raise ValueError(
                f"AgentSpec {self.name}: MVP 阶段仅支持只读子智能体；"
                "副作用类任务走 api/confirm 人工确认链路（第 4 步实现）"
            )


class AgentRegistry:
    """spec 与执行体成对注册；graph 编译（core/graph.py）以本表为节点来源。"""

    def __init__(self) -> None:
        self._specs: dict[str, AgentSpec] = {}
        self._runnables: dict[str, AgentRunnable] = {}

    def register(self, spec: AgentSpec, runnable: AgentRunnable) -> None:
        if spec.name in self._specs:
            raise ValueError(f"子智能体重复注册: {spec.name}")
        self._specs[spec.name] = spec
        self._runnables[spec.name] = runnable

    def get(self, name: str) -> tuple[AgentSpec, AgentRunnable]:
        if name not in self._specs:
            raise KeyError(f"未注册的子智能体: {name}，已注册: {sorted(self._specs)}")
        return self._specs[name], self._runnables[name]

    def spec(self, name: str) -> AgentSpec:
        return self.get(name)[0]

    def specs(self) -> list[AgentSpec]:
        return list(self._specs.values())

    def catalog_for_llm(self) -> str:
        """注入 Orchestrator prompt 的能力清单（name + description + 出入参字段）。"""
        lines = []
        for s in self._specs.values():
            in_fields = ", ".join(s.input_schema.model_fields)
            out_fields = ", ".join(s.output_schema.model_fields)
            lines.append(f"- {s.name}: {s.description}（输入: {in_fields}；输出: {out_fields}）")
        return "\n".join(lines)
