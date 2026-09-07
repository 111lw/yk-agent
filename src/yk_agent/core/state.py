"""Blackboard 共享状态（TripState）与编排相关数据结构。

设计文档：docs/03-agent-orchestration.md。硬规则：
- 编排状态统一在本文件定义，禁止子智能体私自扩展状态字段；
- 子智能体之间禁止点对点传话，一切数据经 TripState 交换。

并行派发会并发写 findings / steps_done / tokens_used，因此这三个字段
必须配 reducer（merge / add），其余字段只会被单个节点写入（覆盖语义）。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

FINDINGS_RESET = "__reset__"  # 哨兵键：携带它写入即整体清空 findings（Critic 回炉重跑用）


def merge_findings(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """findings 合并 reducer：并行子智能体的产出按 agent name 键合并；
    写入含哨兵键的 dict 时整体重置（空 dict 与 left 合并仍是 left，无法表达清空）。"""
    if FINDINGS_RESET in right:
        return {k: v for k, v in right.items() if k != FINDINGS_RESET}
    return {**left, **right}


class PlanTask(BaseModel):
    """计划中的一个任务。MVP 约定：同一 agent 在 plan 中只出现一次（按 name 去重）。"""

    agent: str  # Agent Registry 中的 name
    instruction: str  # 具体任务描述（含依赖产出如何使用）
    depends_on: list[str] = Field(default_factory=list)  # 依赖的 agent name；空 → 可并行派发


class AgentFinding(BaseModel):
    """一个子智能体的结构化产出（或失败记录）。缺失数据优于脏数据。"""

    agent: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)  # output_schema 校验后的产出
    error: str | None = None


class CriticVerdict(BaseModel):
    """Critic 评审结论。passed=False 时 reasons 必须给出可执行的修改方向。"""

    passed: bool
    reasons: list[str] = Field(default_factory=list)


class TripState(TypedDict, total=False):
    # —— 只读上下文（Orchestrator 注入，子智能体不可修改）——
    session_id: str
    user_id: str
    user_profile: dict[str, Any]  # 画像切片（第 3 步接入 UserProfile）
    user_message: str

    # —— 编排控制 ——
    plan: list[dict[str, Any]]  # PlanTask.model_dump() 列表，Orchestrator 可整体重写
    critic_verdict: CriticVerdict | None
    critic_rounds: int  # 已回炉次数，硬规则 ≤ 2（core/guardrails.py）
    confirmation_required: dict[str, Any] | None  # 副作用动作待确认信息（human-in-the-loop）
    final_answer: str | None

    # —— 并发累加字段（必须经 reducer）——
    steps_done: Annotated[int, operator.add]  # 护栏：子智能体每完成一个 +1
    tokens_used: Annotated[int, operator.add]  # 护栏：所有 LLM 调用的 token 累计
    findings: Annotated[dict[str, Any], merge_findings]  # key=agent name → AgentFinding

    # Orchestrator 的推理消息历史（原始产出不回流全文，见执行规则 5）
    messages: Annotated[list[Any], add_messages]
