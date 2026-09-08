"""子智能体注册引导：MVP 三个子智能体在此集中注册（唯一注册点）。

description 是 Orchestrator 的"眼睛"，必须写清【能做什么/输入/输出/何时选它】，
质量直接决定自主编排质量（docs/03-agent-orchestration.md §Agent Registry）。
"""

from __future__ import annotations

from yk_agent.agents.budget_agent import BudgetAgentInput, BudgetAgentOutput, make_budget_agent
from yk_agent.agents.poi_agent import PoiAgentInput, PoiAgentOutput, make_poi_agent
from yk_agent.agents.registry import AgentRegistry, AgentSpec
from yk_agent.agents.route_agent import RouteAgentInput, RouteAgentOutput, make_route_agent
from yk_agent.mcp.map.provider import MapProvider


def build_default_registry(map_provider: MapProvider) -> AgentRegistry:
    """以给定 map provider 构建默认注册表（测试可注入 MockMapProvider）。"""
    registry = AgentRegistry()
    registry.register(
        AgentSpec(
            name="poi-agent",
            description=(
                "检索目的地 POI 候选（景点/餐饮/住宿）。输入城市与关键词（instruction 需携带"
                " '城市=xx 关键词=xx,yy' 片段），返回经过用户画像 dislike 硬过滤的候选列表"
                "（含名称/分类/坐标/评分）。任何需要具体地点候选的场景都应先调用它。"
            ),
            input_schema=PoiAgentInput,
            output_schema=PoiAgentOutput,
            graph_node="poi-agent",
        ),
        make_poi_agent(map_provider),
    )
    registry.register(
        AgentSpec(
            name="route-agent",
            description=(
                "把 poi-agent 的候选编排成逐日行程（上午/下午/晚间各一个活动）。依赖 poi-agent"
                " 的产出，instruction 需携带 '天数=N' 片段。产出按天的活动安排与未排入候选数。"
            ),
            input_schema=RouteAgentInput,
            output_schema=RouteAgentOutput,
            graph_node="route-agent",
        ),
        make_route_agent(),
    )
    registry.register(
        AgentSpec(
            name="budget-agent",
            description=(
                "按 route-agent 的逐日行程测算分项预算（住宿/餐饮/门票/市内交通，大交通未含）。"
                "依赖 route-agent 产出，instruction 需携带 '天数=N' 片段。"
                "产出总额、分项与估算口径。"
            ),
            input_schema=BudgetAgentInput,
            output_schema=BudgetAgentOutput,
            graph_node="budget-agent",
        ),
        make_budget_agent(),
    )
    return registry
