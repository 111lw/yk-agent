"""高德开放平台 REST adapter（v3 接口）。

文档：https://lbs.amap.com/api/webservice/summary
错误约定：高德返回 status=0 时抛 AmapError，由 run_tool 收敛为结构化失败。
"""

from __future__ import annotations

import httpx

from yk_agent.mcp.contracts.map import (
    GeocodeRequest,
    GeocodeResponse,
    Poi,
    PoiSearchRequest,
    PoiSearchResponse,
    RoutePlanRequest,
    RoutePlanResponse,
)

_BASE = "https://restapi.amap.com/v3"
_PAGE_SIZE = 25  # 契约上限（docs/07-mcp-tools.md）


class AmapError(RuntimeError):
    pass


class AmapProvider:
    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._key = api_key
        self._client = client or httpx.AsyncClient(timeout=8.0)

    async def _get(self, path: str, params: dict) -> dict:
        params = {"key": self._key, **params}
        resp = await self._client.get(f"{_BASE}{path}", params=params)
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "1":
            raise AmapError(f"高德错误 {body.get('infocode')}: {body.get('info')}")
        return body

    async def geocode(self, req: GeocodeRequest) -> GeocodeResponse:
        body = await self._get("/geocode/geo", {"address": req.address, "city": req.city})
        geocodes = body.get("geocodes") or []
        if not geocodes:
            raise AmapError(f"无法解析地址: {req.city} {req.address}")
        first = geocodes[0]
        lng, lat = first["location"].split(",")
        return GeocodeResponse(lng=float(lng), lat=float(lat), level=first.get("level"))

    async def poi_search(self, req: PoiSearchRequest) -> PoiSearchResponse:
        params: dict = {
            "keywords": req.keywords,
            "city": req.city,
            "citylimit": "true",
            "offset": _PAGE_SIZE,
            "page": req.page,
        }
        if req.category:
            params["types"] = req.category
        path = "/place/text"
        if req.location:
            path = "/place/around"
            radius = int(req.radius_km * 1000)
            params |= {"location": req.location.replace(" ", ""), "radius": radius}
        body = await self._get(path, params)
        pois = [
            Poi(
                poi_id=p.get("id", ""),
                name=p.get("name", ""),
                category=(p.get("type") or "").split(";")[0] or None,
                location=p.get("location", "").replace(" ", ""),
                address=p.get("address") or None,
                # biz_ext.rating / cost 为可选字段，缺失即 None（缺失数据优于脏数据）
                rating=float(r) if (r := (p.get("biz_ext") or {}).get("rating")) else None,
                price_level=int(float(c)) if (c := (p.get("biz_ext") or {}).get("cost")) else None,
            )
            for p in body.get("pois", [])
        ]
        return PoiSearchResponse(pois=pois, total=int(body.get("count", len(pois))))

    async def route_plan(self, req: RoutePlanRequest) -> RoutePlanResponse:
        if req.mode == "transit":
            # 公交路径规划返回结构与驾车差异大且分城市实时数据，MVP 先结构化降级
            raise AmapError("transit 模式 MVP 暂未接入，请用 driving/walking")
        path = "/direction/driving" if req.mode == "driving" else "/direction/walking"
        params: dict = {
            "origin": req.origin.replace(" ", ""),
            "destination": req.destination.replace(" ", ""),
        }
        if req.waypoints:
            params["waypoints"] = ";".join(w.replace(" ", "") for w in req.waypoints)
        body = await self._get(path, params)
        route = body.get("route") or {}
        paths = route.get("paths") or []
        if not paths:
            raise AmapError("未找到可行路径")
        p = paths[0]
        steps = [s.get("instruction", "") for s in p.get("steps", [])][:10]
        return RoutePlanResponse(
            distance_km=round(float(p.get("distance", 0)) / 1000, 1),
            duration_min=round(float(p.get("duration", 0)) / 60, 0),
            steps_summary=steps,
        )
