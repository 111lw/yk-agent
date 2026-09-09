"""poi-agent：按城市+偏好检索景点/餐饮/住宿 POI 候选。

画像联动（docs/04-user-profile.md §双通道）：dislike 项对 POI 名称/分类做
硬过滤（关键词映射表），like 项仅作排序加权，绝不武断丢弃。
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from yk_agent.agents.base import AgentPayload, parse_slot
from yk_agent.knowledge.retriever import KbRetriever
from yk_agent.mcp.base import run_tool
from yk_agent.mcp.contracts.map import Poi, PoiSearchRequest
from yk_agent.mcp.map.provider import MapProvider

logger = logging.getLogger(__name__)

# dislike 规范值 → 中文名称关键词（命中即硬过滤）。新规范值接入时在此登记。
DISLIKE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hiking": ("山", "登山", "徒步", "爬"),
    "seafood": ("海鲜",),
    "nightlife": ("酒吧", "夜店", "夜生活"),
    "museum": ("博物馆", "纪念馆"),
    "temple": ("寺", "庙"),
}


class PoiAgentInput(AgentPayload):
    pass  # 城市/关键词从 instruction 的 "城市=xx 关键词=xx" 片段解析


class PoiAgentOutput(BaseModel):
    city: str
    keywords: list[str]
    pois: list[Poi] = Field(default_factory=list)  # 已过画像 dislike 硬过滤
    filtered_count: int = 0  # 被画像过滤掉的数量（可解释性用）
    kb_tips: list[str] = Field(default_factory=list)  # 知识库召回的目的地攻略要点
    note: str = ""


def _dislike_values(profile: dict) -> list[str]:
    prefs = profile.get("preferences", []) if isinstance(profile, dict) else []
    return [
        p.get("value", "")
        for p in prefs
        if isinstance(p, dict)
        and p.get("sentiment") == "dislike"
        and abs(p.get("weight", 0)) >= 0.5
    ]


def _matches_dislike(poi: Poi, dislikes: list[str]) -> bool:
    for value in dislikes:
        for kw in DISLIKE_KEYWORDS.get(value, ()):
            if kw in poi.name or kw in (poi.category or ""):
                return True
    return False


def make_poi_agent(map_provider: MapProvider, kb: KbRetriever | None = None):
    """工厂：注入地图 provider 与可选知识库检索器，返回 Registry 注册用执行体。"""

    async def run(payload: dict) -> dict:
        req = PoiAgentInput.model_validate(payload)
        city = parse_slot(req.instruction, "城市")
        if not city:
            raise ValueError(
                f"poi-agent 需要 instruction 携带 '城市=xx' 片段，收到: {req.instruction!r}"
            )
        keywords_str = parse_slot(req.instruction, "关键词", stop_at_comma=False) or "景点"
        keywords = [k.strip() for k in keywords_str.replace("，", ",").split(",") if k.strip()]

        dislikes = _dislike_values(req.user_profile)
        all_pois: list[Poi] = []
        failed: list[str] = []
        for kw in keywords[:3]:  # 关键词上限 3，控制工具调用量
            result = await run_tool(
                "poi_search", map_provider.poi_search, PoiSearchRequest(city=city, keywords=kw)
            )
            if result.ok and result.data:
                all_pois.extend(result.data.pois)
            else:
                failed.append(kw)

        # 按 poi_id 去重后过画像硬过滤
        seen: set[str] = set()
        unique: list[Poi] = []
        for p in all_pois:
            if p.poi_id not in seen:
                seen.add(p.poi_id)
                unique.append(p)
        kept = [p for p in unique if not _matches_dislike(p, dislikes)]

        note = ""
        if failed:
            note = f"关键词 {failed} 检索失败（降级：缺失该类候选）"

        # 知识库补充目的地攻略要点（失败静默跳过，不影响 POI 主产出）
        kb_tips: list[str] = []
        if kb is not None:
            try:
                hits = await kb.search(f"{city} 攻略 玩法", city=city, top_k=3)
                kb_tips = [h["content"] for h in hits]
            except Exception as e:  # noqa: BLE001
                logger.warning("poi-agent 知识库检索失败（跳过）: %s", e)

        return PoiAgentOutput(
            city=city,
            keywords=keywords,
            pois=kept,
            filtered_count=len(unique) - len(kept),
            kb_tips=kb_tips,
            note=note,
        ).model_dump()

    return run
