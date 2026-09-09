"""自主编排 graph：Plan-and-Execute + Send 动态并行派发 + Critic 回环。

拓扑（docs/03-agent-orchestration.md §LangGraph 拓扑）：

    START → orchestrator ──(路由: 有就绪任务)──→ Send×N → 子智能体节点群
                 ↑                                           │
                 │──(critic 不通过且未超回炉上限)── critic ←───┘
                 └──(计划完成)────────────────────┘
    路由/评审任一终态 → responder(生成 final_answer) → END

本模块只依赖 LLMProvider 抽象与 AgentRegistry，不感知具体子智能体。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from yk_agent.agents.registry import AgentRegistry
from yk_agent.core.guardrails import blocked_by_guardrail, critic_rounds_exhausted
from yk_agent.core.state import FINDINGS_RESET, AgentFinding, CriticVerdict, PlanTask, TripState
from yk_agent.llm.json_utils import chat_validated_detailed
from yk_agent.llm.models import ChatMessage
from yk_agent.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

ORCHESTRATOR = "orchestrator"
CRITIC = "critic"
RESPONDER = "responder"

_ORCH_SYSTEM = """你是旅游智能体的编排者。根据用户请求与可用子智能体，制定结构化任务计划。

可用子智能体：
{catalog}

规则：
1. 只能使用上面列出的子智能体；每个子智能体在计划中最多出现一次。
2. depends_on 填写该任务依赖的其他子智能体 name；无依赖则留空数组，无依赖任务将并行执行。
3. instruction 要具体到子智能体可以直接执行，并说明依赖产出如何使用。
4. 与旅游无关的请求，plan 返回空数组。
5. 若已完成的产出显示某子智能体结果为空或失败，不要在修订计划中原样重复派发同一任务——
   要么给出改写后更可行的指令，要么接受该数据缺失并省略此任务。
只输出 JSON。"""

_ORCH_USER = (
    "用户画像摘要（规划须与其一致，dislike 项不得安排）：\n{profile}\n\n用户请求：{message}"
)

_ORCH_REVISE_USER = """上一轮产出未通过评审，问题：
{reasons}

已完成的产出摘要：
{findings}

请重新制定完整计划（可调整任务内容与依赖，重跑不合格的部分）。
注意：对上一轮已失败或产出为空的任务，不要原样重复派发（见系统规则 5）。用户请求：{message}"""

_CRITIC_SYSTEM = """你是旅游攻略评审员。基于各子智能体的产出，判断当前结果是否足以生成一份
对用户合理的回答（信息是否齐备、有无明显矛盾）。不足时给出具体、可执行的修改方向。
只输出 JSON，字段：passed (bool)、reasons (string[])。"""

_RESPONDER_SYSTEM = (
    "你是懂用户的旅行顾问。基于已有产出生成最终回答，"
    "引用画像依据解释推荐理由；产出缺失的部分如实说明，不要编造。"
)


class _PlanOutput(BaseModel):
    """Orchestrator 规划 / 修订的 LLM 结构化输出。"""

    plan: list[PlanTask] = Field(default_factory=list)


def build_graph(registry: AgentRegistry, provider: LLMProvider, skills: Sequence[str] = ()):
    """以 Registry 为节点来源编译编排 graph。

    skills：装载的 SKILL.md 正文（docs/06-skills-spec.md），注入 responder 的 system prompt。
    checkpoint 传入方（api 层第 4 步接 Postgres saver）用于 human-in-the-loop 恢复。
    """

    # ---------- Orchestrator：首次规划 / 评审后修订 ----------

    async def orchestrator_node(state: TripState) -> dict[str, Any]:
        findings: dict[str, Any] = state.get("findings", {})
        verdict: CriticVerdict | None = state.get("critic_verdict")

        if state.get("plan") and verdict is None:
            # 从子智能体返回：计划已在执行中，无需重新规划（路由函数决定下一步）
            return {}

        if verdict is not None and not verdict.passed:
            # 评审不通过 → 修订：重置全部 findings，按新计划重跑（回炉语义，MVP 简化）
            user_prompt = _ORCH_REVISE_USER.format(
                reasons="\n".join(f"- {r}" for r in verdict.reasons),
                findings=json.dumps(findings, ensure_ascii=False),
                message=state["user_message"],
            )
            messages = [
                ChatMessage(
                    role="system", content=_ORCH_SYSTEM.format(catalog=registry.catalog_for_llm())
                ),
                ChatMessage(role="user", content=user_prompt),
            ]
            result, llm_resp = await chat_validated_detailed(provider, messages, _PlanOutput)
            return {
                "plan": [t.model_dump() for t in result.plan],
                "critic_verdict": None,
                "findings": {FINDINGS_RESET: None},  # 哨兵整体重置：回炉重跑
                "tokens_used": llm_resp.usage.total_tokens,
                "messages": [
                    {"role": "assistant", "content": f"plan-revision: {result.model_dump_json()}"}
                ],
            }

        # 首次进入：规划
        messages = [
            ChatMessage(
                role="system", content=_ORCH_SYSTEM.format(catalog=registry.catalog_for_llm())
            ),
            ChatMessage(
                role="user",
                content=_ORCH_USER.format(
                    profile=json.dumps(state.get("user_profile", {}), ensure_ascii=False),
                    message=state["user_message"],
                ),
            ),
        ]
        result, llm_resp = await chat_validated_detailed(provider, messages, _PlanOutput)
        return {
            "plan": [t.model_dump() for t in result.plan],
            "tokens_used": llm_resp.usage.total_tokens,
            "messages": [{"role": "assistant", "content": f"plan: {result.model_dump_json()}"}],
        }

    def route_from_orchestrator(state: TripState) -> str | list[Send]:
        if blocked_by_guardrail(state):
            return RESPONDER
        plan = [PlanTask.model_validate(t) for t in state.get("plan", [])]
        done = set(state.get("findings", {}))
        pending = [t for t in plan if t.agent not in done]
        if not pending:
            return CRITIC
        ready = [t for t in pending if all(d in done for d in t.depends_on)]
        if not ready:
            # 剩余任务依赖永不满足（上游失败）→ 降级送审，缺失数据优于死等
            return CRITIC
        sends = []
        for t in ready:
            # 副作用任务在 AgentSpec 注册时即被禁止（MVP 仅只读子智能体），
            # 确认链路待 api/confirm 人工确认机制实现后放开
            upstream = {d: state["findings"][d] for d in t.depends_on}
            payload = {
                "agent": t.agent,
                "instruction": t.instruction,
                "user_message": state["user_message"],
                "user_profile": state.get("user_profile", {}),
                "upstream": upstream,
            }
            sends.append(Send(spec.graph_node, payload))
        return sends

    # ---------- 子智能体节点（按 Registry 工厂生成）----------

    async def run_agent(payload: dict[str, Any]) -> dict[str, Any]:
        name = payload["agent"]
        spec, runnable = registry.get(name)
        try:
            spec.input_schema.model_validate(payload)  # 入参契约校验
            raw = await runnable(payload)
            out = spec.output_schema.model_validate(raw)  # 出参契约校验
            finding = AgentFinding(agent=name, ok=True, data=out.model_dump())
        except Exception as e:  # noqa: BLE001 — 任何失败降级为缺失产出，不阻塞编排
            logger.warning("子智能体 %s 执行失败: %s", name, e)
            finding = AgentFinding(agent=name, ok=False, error=str(e))
        return {"findings": {name: finding.model_dump()}, "steps_done": 1}

    # ---------- Critic ----------

    async def critic_node(state: TripState) -> dict[str, Any]:
        result, llm_resp = await chat_validated_detailed(
            provider,
            [
                ChatMessage(role="system", content=_CRITIC_SYSTEM),
                ChatMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "user_message": state["user_message"],
                            "findings": state.get("findings", {}),
                        },
                        ensure_ascii=False,
                    ),
                ),
            ],
            CriticVerdict,
        )
        return {
            "critic_verdict": result,
            "critic_rounds": state.get("critic_rounds", 0) + (0 if result.passed else 1),
            "tokens_used": llm_resp.usage.total_tokens,
        }

    def route_from_critic(state: TripState) -> str:
        verdict = state.get("critic_verdict")
        if verdict and verdict.passed:
            return RESPONDER
        if critic_rounds_exhausted(state):
            return RESPONDER  # 超限：带瑕疵输出并标注
        return ORCHESTRATOR

    # ---------- Responder ----------

    async def responder_node(state: TripState) -> dict[str, Any]:
        system = _RESPONDER_SYSTEM
        if skills:
            system = system + "\n\n" + "\n\n---\n\n".join(skills)
        findings = state.get("findings", {})
        verdict = state.get("critic_verdict")
        prefix = ""
        if verdict is not None and not verdict.passed:
            prefix = "（注意：以下内容可能存在以下方面瑕疵：" + "；".join(verdict.reasons) + "）\n"
        if blocked_by_guardrail(state):
            prefix += "（注意：任务复杂度超出本单次处理上限，以下为基于部分产出的结果。）\n"

        result = await provider.chat(
            [
                ChatMessage(role="system", content=_RESPONDER_SYSTEM),
                ChatMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "user_message": state["user_message"],
                            "user_profile": state.get("user_profile", {}),
                            "findings": findings,
                        },
                        ensure_ascii=False,
                    ),
                ),
            ]
        )
        return {
            "final_answer": prefix + result.content,
            "tokens_used": result.usage.total_tokens,
        }

    # ---------- 组装 ----------

    builder = StateGraph(TripState)
    builder.add_node(ORCHESTRATOR, orchestrator_node)
    builder.add_node(CRITIC, critic_node)
    builder.add_node(RESPONDER, responder_node)
    for spec in registry.specs():
        builder.add_node(spec.graph_node, run_agent)
        builder.add_edge(spec.graph_node, ORCHESTRATOR)

    builder.add_edge(START, ORCHESTRATOR)
    # orchestrator 路由会返回 Send 动态指向子智能体节点，故不声明静态 path_map
    builder.add_conditional_edges(ORCHESTRATOR, route_from_orchestrator)
    builder.add_conditional_edges(CRITIC, route_from_critic, [ORCHESTRATOR, RESPONDER])
    builder.add_edge(RESPONDER, END)

    return builder.compile()
