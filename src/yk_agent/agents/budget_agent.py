"""budget-agent：行程分项预算测算（交通/住宿/门票/餐饮）。

MVP 用估算系数表（确定性、可解释），price_level 等真实数据接入后细化。
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from yk_agent.agents.base import AgentPayload, parse_int_slot

logger = logging.getLogger(__name__)

# 估算系数（元）。口径：三线旅游城市人均，MVP 简化；来源与调整记录在 docs/07。
_RATES = {
    "hotel_per_night": 300.0,
    "meal_per_day": 150.0,
    "ticket_per_poi": 60.0,
    "local_transport_per_day": 80.0,
}


class BudgetAgentInput(AgentPayload):
    pass


class BudgetAgentOutput(BaseModel):
    currency: str = "CNY"
    total: float
    per_day: float
    breakdown: dict[str, float]
    assumptions: list[str] = Field(default_factory=list)  # 估算口径，输出中如实呈现


def make_budget_agent():
    async def run(payload: dict) -> dict:
        req = BudgetAgentInput.model_validate(payload)
        days_n = parse_int_slot(req.instruction, "天数", 3)

        route_finding = (req.upstream.get("route-agent") or {}).get("data") or {}
        day_plans = route_finding.get("days", [])
        poi_count = sum(len(d.get("activities", [])) for d in day_plans)
        if not day_plans:
            raise ValueError("budget-agent 需要 route-agent 的产出（upstream 缺失或为空）")

        nights = max(days_n - 1, 1)
        breakdown = {
            "住宿": round(_RATES["hotel_per_night"] * nights, 1),
            "餐饮": round(_RATES["meal_per_day"] * days_n, 1),
            "门票": round(_RATES["ticket_per_poi"] * poi_count, 1),
            "市内交通": round(_RATES["local_transport_per_day"] * days_n, 1),
        }
        total = round(sum(breakdown.values()), 1)
        assumptions = [
            f"住宿 {_RATES['hotel_per_night']:.0f} 元/晚 × {nights} 晚",
            f"餐饮 {_RATES['meal_per_day']:.0f} 元/天 × {days_n} 天",
            f"门票 {_RATES['ticket_per_poi']:.0f} 元/景点 × {poi_count} 个（估算）",
            "大交通（往返机票/火车）未含，需按出发地补充",
        ]
        return BudgetAgentOutput(
            total=total,
            per_day=round(total / days_n, 1),
            breakdown=breakdown,
            assumptions=assumptions,
        ).model_dump()

    return run
