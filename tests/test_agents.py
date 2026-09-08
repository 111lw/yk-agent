"""子智能体单测 + 全链路集成测试（真子智能体 + MockMap + MockLLM，全离线）。

覆盖 docs/03 执行规则在真实子智能体上的表现：依赖链 poi→route→budget、
画像 dislike 硬过滤、instruction 结构化片段解析、产出契约校验。
"""

import json
from typing import Any

import pytest

from yk_agent.agents.bootstrap import build_default_registry
from yk_agent.agents.budget_agent import make_budget_agent
from yk_agent.agents.poi_agent import make_poi_agent
from yk_agent.agents.route_agent import make_route_agent
from yk_agent.core.graph import build_graph
from yk_agent.llm.mock import MockLLMProvider
from yk_agent.mcp.map.provider import MockMapProvider
from yk_agent.skills.loader import load_skill


def _payload(
    instruction: str, upstream: dict[str, Any] | None = None, profile: dict | None = None
) -> dict:
    return {
        "agent": "x",
        "instruction": instruction,
        "user_message": "想去大理玩3天",
        "user_profile": profile or {},
        "upstream": upstream or {},
    }


_PROFILE_DISLIKE_HIKING = {
    "preferences": [
        {"dimension": "interest", "value": "hiking", "sentiment": "dislike", "weight": -0.8}
    ]
}


# ---------- poi-agent 单测 ----------


async def test_poi_agent_parses_slot_and_filters_dislike():
    run = make_poi_agent(MockMapProvider())
    out = await run(_payload("城市=大理 关键词=景点,美食", profile=_PROFILE_DISLIKE_HIKING))
    assert out["city"] == "大理"
    assert out["keywords"] == ["景点", "美食"]
    names = [p["name"] for p in out["pois"]]
    assert all("山" not in n for n in names)  # dislike hiking → 苍山景区被硬过滤
    assert out["filtered_count"] >= 1  # 且留下了可解释的过滤记录


async def test_poi_agent_requires_city_slot():
    run = make_poi_agent(MockMapProvider())
    with pytest.raises(ValueError, match="城市="):
        await run(_payload("帮我找点好玩的"))


# ---------- route/budget 单测 ----------


async def test_route_agent_requires_upstream():
    run = make_route_agent()
    with pytest.raises(ValueError, match="poi-agent"):
        await run(_payload("天数=3"))


async def test_budget_agent_requires_upstream():
    run = make_budget_agent()
    with pytest.raises(ValueError, match="route-agent"):
        await run(_payload("天数=3"))


# ---------- skills loader ----------


def test_load_trip_planner_skill():
    body = load_skill("trip-planner")
    assert "方法论" in body and "---" not in body.split("\n")[0]  # frontmatter 已剥离


def test_load_missing_skill_raises():
    with pytest.raises(FileNotFoundError):
        load_skill("no-such-skill")


# ---------- 全链路集成：真子智能体走完整编排 ----------


def _plan() -> str:
    return json.dumps(
        {
            "plan": [
                {
                    "agent": "poi-agent",
                    "instruction": "城市=大理 关键词=景点,美食",
                    "depends_on": [],
                },
                {"agent": "route-agent", "instruction": "天数=3", "depends_on": ["poi-agent"]},
                {"agent": "budget-agent", "instruction": "天数=3", "depends_on": ["route-agent"]},
            ]
        },
        ensure_ascii=False,
    )


async def test_full_pipeline_with_real_subagents():
    registry = build_default_registry(MockMapProvider())
    graph = build_graph(
        registry,
        MockLLMProvider([_plan(), json.dumps({"passed": True, "reasons": []}), "这是最终攻略"]),
        skills=[load_skill("trip-planner")],
    )
    result = await graph.ainvoke(
        {
            "session_id": "s1",
            "user_id": "u1",
            "user_message": "想去大理玩3天，预算3000，不想爬山",
            "user_profile": _PROFILE_DISLIKE_HIKING,
        }
    )

    # 依赖链完整：三个产出都在
    assert set(result["findings"]) == {"poi-agent", "route-agent", "budget-agent"}
    assert all(f["ok"] for f in result["findings"].values())

    poi = result["findings"]["poi-agent"]["data"]
    route = result["findings"]["route-agent"]["data"]
    budget = result["findings"]["budget-agent"]["data"]

    # 画像 dislike 硬过滤生效
    assert poi["filtered_count"] >= 1
    assert all("山" not in p["name"] for p in poi["pois"])
    # route 消费 poi：逐日行程里不含被过滤的 POI
    assert len(route["days"]) == 3
    day1_names = {a["name"] for a in route["days"][0]["activities"]}
    assert day1_names and all("山" not in n for n in day1_names)
    # budget 消费 route：分项齐全、总额为正
    assert set(budget["breakdown"]) == {"住宿", "餐饮", "门票", "市内交通"}
    assert budget["total"] > 0

    assert result["final_answer"] == "这是最终攻略"
    assert result["steps_done"] == 3
