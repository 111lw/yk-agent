"""自主编排集成测试：MockLLM + 假子智能体跑通完整循环，不发真实请求。

覆盖 docs/03-agent-orchestration.md 的核心行为：
计划先行 / 并行派发 / 依赖顺序 / Critic 回炉 / 护栏收敛 / 失败降级 / Registry 约束。
"""

import json
from typing import Any

import pytest
from pydantic import BaseModel

from yk_agent.agents.registry import AgentRegistry, AgentSpec
from yk_agent.core.graph import build_graph
from yk_agent.llm.mock import MockLLMProvider


class _DictIn(BaseModel):
    """宽松入参：假子智能体不关心契约细节，只验证链路。"""


class _OutA(BaseModel):
    value: str


def _plan(*tasks: dict[str, Any]) -> str:
    return json.dumps({"plan": list(tasks)}, ensure_ascii=False)


def _pass() -> str:
    return json.dumps({"passed": True, "reasons": []})


def _fail(reason: str) -> str:
    return json.dumps({"passed": False, "reasons": [reason]}, ensure_ascii=False)


def _make_registry() -> AgentRegistry:
    registry = AgentRegistry()

    async def run_a(payload: dict) -> dict:
        return {"value": "A完成"}

    async def run_b(payload: dict) -> dict:
        upstream = payload.get("upstream", {}).get("a-agent", {}).get("data", {})
        return {"value": f"B收到[{upstream.get('value')}]"}

    async def run_c(payload: dict) -> dict:
        return {"value": "C完成"}

    registry.register(AgentSpec("a-agent", "独立任务A（测试）", _DictIn, _OutA, "a-agent"), run_a)
    registry.register(
        AgentSpec("b-agent", "依赖A的任务B（测试）", _DictIn, _OutA, "b-agent"), run_b
    )
    registry.register(AgentSpec("c-agent", "独立任务C（测试）", _DictIn, _OutA, "c-agent"), run_c)
    return registry


def _graph(mock_responses: list[str]):
    return build_graph(_make_registry(), MockLLMProvider(mock_responses))


_BASE = {"session_id": "s1", "user_id": "u1", "user_profile": {}, "user_message": "想去大理"}


async def test_full_flow_plan_dispatch_critic_respond():
    """计划 → 派发 → 评审通过 → 最终回答，产出与依赖传递全部正确。"""
    graph = _graph(
        [
            _plan(
                {"agent": "a-agent", "instruction": "做A", "depends_on": []},
                {"agent": "b-agent", "instruction": "用A的结果做B", "depends_on": ["a-agent"]},
            ),
            _pass(),
            "最终回答文本",
        ]
    )
    result = await graph.ainvoke(dict(_BASE))

    assert result["final_answer"] == "最终回答文本"
    assert result["findings"]["a-agent"]["ok"] is True
    assert result["findings"]["b-agent"]["ok"] is True
    # 依赖传递验证：B 收到了 A 的产出
    assert "B收到[A完成]" in result["findings"]["b-agent"]["data"]["value"]
    assert result["steps_done"] == 2


async def test_parallel_dispatch_no_deps():
    """无依赖任务全部被派发完成（并行 Send 的结果合并进 findings）。"""
    graph = _graph(
        [
            _plan(
                {"agent": "a-agent", "instruction": "做A", "depends_on": []},
                {"agent": "c-agent", "instruction": "做C", "depends_on": []},
            ),
            _pass(),
            "回答",
        ]
    )
    result = await graph.ainvoke(dict(_BASE))
    assert set(result["findings"]) == {"a-agent", "c-agent"}
    assert result["steps_done"] == 2


async def test_critic_rejection_triggers_revision_and_rerun():
    """Critic 不通过 → 回炉重规划（findings 重置）→ 重新派发 → 通过。"""
    graph = _graph(
        [
            _plan({"agent": "a-agent", "instruction": "做A", "depends_on": []}),
            _fail("缺少预算明细"),
            _plan({"agent": "a-agent", "instruction": "重做A", "depends_on": []}),
            _pass(),
            "回炉后的回答",
        ]
    )
    result = await graph.ainvoke(dict(_BASE))
    assert result["final_answer"] == "回炉后的回答"
    assert result["critic_rounds"] == 1
    assert result["findings"]["a-agent"]["data"]["value"] == "A完成"  # 重跑后产出恢复


async def test_critic_gives_up_after_max_rounds():
    """连续两轮评审不通过 → 强制收敛输出，且最终回答带瑕疵标注。"""
    graph = _graph(
        [
            _plan({"agent": "a-agent", "instruction": "做A", "depends_on": []}),
            _fail("问题一"),
            _plan({"agent": "a-agent", "instruction": "重做A", "depends_on": []}),
            _fail("问题二"),
            "带瑕疵的回答",
        ]
    )
    result = await graph.ainvoke(dict(_BASE))
    assert result["final_answer"].startswith("（注意：以下内容可能存在以下方面瑕疵")
    assert "问题二" in result["final_answer"]


async def test_guardrail_steps_force_convergence():
    """步数护栏触发：跳过 Critic 直接收敛，回答带降级标注。"""
    import yk_agent.core.guardrails as guardrails

    original = guardrails._limits
    guardrails._limits = lambda: (1, 10**9)  # 步数上限压到 1
    try:
        graph = _graph(
            [
                _plan(
                    {"agent": "a-agent", "instruction": "做A", "depends_on": []},
                    {"agent": "c-agent", "instruction": "做C", "depends_on": []},
                ),
                "降级回答",
            ]
        )
        result = await graph.ainvoke(dict(_BASE))
        assert "超出本单次处理上限" in result["final_answer"]
        assert "critic_verdict" not in result or result["critic_verdict"] is None
    finally:
        guardrails._limits = original


async def test_agent_failure_degrades_not_blocks():
    """子智能体抛异常 → 记为失败产出，编排继续，回答如实产出。"""
    registry = AgentRegistry()

    async def run_broken(payload: dict) -> dict:
        raise RuntimeError("模拟工具超时")

    registry.register(
        AgentSpec("broken-agent", "必然失败的任务（测试）", _DictIn, _OutA, "broken-agent"),
        run_broken,
    )

    graph = build_graph(
        registry,
        MockLLMProvider([_plan({"agent": "broken-agent", "instruction": "x"}), _pass(), "回答"]),
    )
    result = await graph.ainvoke(dict(_BASE))
    assert result["findings"]["broken-agent"]["ok"] is False
    assert "模拟工具超时" in result["findings"]["broken-agent"]["error"]
    assert result["final_answer"] == "回答"


async def test_non_travel_intent_no_dispatch():
    """非旅游意图：计划为空 → 不派发任何子智能体，直接走评审与回答。"""
    graph = _graph([_plan(), _pass(), "我只能帮你规划旅行哦"])
    result = await graph.ainvoke({**_BASE, "user_message": "帮我写周报"})
    assert result["steps_done"] == 0
    assert result["final_answer"] == "我只能帮你规划旅行哦"


async def test_unsatisfiable_deps_degrades_to_critic():
    """依赖了不存在的产出 → 不死等，降级送审。"""
    graph = _graph(
        [
            _plan({"agent": "b-agent", "instruction": "做B", "depends_on": ["不存在-agent"]}),
            _pass(),
            "回答",
        ]
    )
    result = await graph.ainvoke(dict(_BASE))
    assert result["steps_done"] == 0
    assert result["final_answer"] == "回答"


async def test_registry_rejects_side_effect_agent():
    """硬规则：MVP 禁止注册有副作用的子智能体。"""
    with pytest.raises(ValueError, match="副作用"):
        AgentSpec("bad-agent", "下单类任务", _DictIn, _OutA, "bad-agent", side_effect=True)


async def test_registry_rejects_duplicate_name():
    registry = AgentRegistry()

    async def run(payload: dict) -> dict:
        return {"value": "x"}

    registry.register(AgentSpec("dup", "任务", _DictIn, _OutA, "dup"), run)
    with pytest.raises(ValueError, match="重复注册"):
        registry.register(AgentSpec("dup", "任务", _DictIn, _OutA, "dup"), run)


async def test_agent_output_schema_violation_recorded_as_failure():
    """产出不符合 output_schema → 校验失败降级为失败产出，不抛穿编排。"""
    registry = AgentRegistry()

    async def run_bad(payload: dict) -> dict:
        return {"wrong_field": 123}  # 缺少 value 字段

    registry.register(
        AgentSpec("schema-violator", "产出不合规的任务（测试）", _DictIn, _OutA, "schema-violator"),
        run_bad,
    )
    graph = build_graph(
        registry,
        MockLLMProvider([_plan({"agent": "schema-violator", "instruction": "x"}), _pass(), "回答"]),
    )
    result = await graph.ainvoke(dict(_BASE))
    assert result["findings"]["schema-violator"]["ok"] is False
