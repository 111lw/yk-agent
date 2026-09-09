"""route-agent：把 poi-agent 的候选串成逐日行程（地理/时间合理性）。

MVP 确定性算法：按天轮转分配候选（每天 3 个：上午/下午/晚间），
真实动线优化（地理聚类 + 顺路）属 V2，用 map route_plan 精算。
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from yk_agent.agents.base import AgentPayload, parse_int_slot

logger = logging.getLogger(__name__)

_PER_DAY = 3  # 每天时段数：上午/下午/晚间
_SLOTS = ("上午", "下午", "晚间")


class Activity(BaseModel):
    slot: str
    poi_id: str
    name: str
    location: str


class DayPlan(BaseModel):
    day: int
    activities: list[Activity] = Field(default_factory=list)


class RouteAgentInput(AgentPayload):
    pass


class RouteAgentOutput(BaseModel):
    days: list[DayPlan]
    uncovered_pois: int = 0  # 候选多于行程容量时未排入的数量


def make_route_agent():
    async def run(payload: dict) -> dict:
        req = RouteAgentInput.model_validate(payload)
        days_n = parse_int_slot(req.instruction, "天数", 3)

        poi_finding = (req.upstream.get("poi-agent") or {}).get("data") or {}
        candidate_pois = poi_finding.get("pois", [])
        if not candidate_pois:
            raise ValueError("route-agent 需要 poi-agent 的产出（upstream 缺失或为空）")

        capacity = days_n * _PER_DAY
        scheduled = candidate_pois[:capacity]
        days = [
            DayPlan(
                day=d + 1,
                activities=[
                    Activity(
                        slot=_SLOTS[i], poi_id=p["poi_id"], name=p["name"], location=p["location"]
                    )
                    for i, p in enumerate(scheduled[d * _PER_DAY : (d + 1) * _PER_DAY])
                ],
            )
            for d in range(days_n)
        ]
        uncovered = max(0, len(candidate_pois) - capacity)
        return RouteAgentOutput(days=days, uncovered_pois=uncovered).model_dump()

    return run
