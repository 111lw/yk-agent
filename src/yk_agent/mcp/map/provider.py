"""MapProvider 协议 + Mock 实现 + 进程内 TTL 缓存包装。"""

from __future__ import annotations

import time
from typing import Any, Protocol

from yk_agent.mcp.contracts.map import (
    GeocodeRequest,
    GeocodeResponse,
    PoiSearchRequest,
    PoiSearchResponse,
    RoutePlanRequest,
    RoutePlanResponse,
)


class MapProvider(Protocol):
    """map-mcp 三个工具的统一接口。实现方内部网络错误直接抛出，
    由 run_tool 收敛为结构化失败（docs/07-mcp-tools.md §设计原则 3）。"""

    async def geocode(self, req: GeocodeRequest) -> GeocodeResponse: ...

    async def poi_search(self, req: PoiSearchRequest) -> PoiSearchResponse: ...

    async def route_plan(self, req: RoutePlanRequest) -> RoutePlanResponse: ...


class MockMapProvider:
    """确定性假数据：POI 名称带上城市前缀，便于测试断言与离线演示。"""

    async def geocode(self, req: GeocodeRequest) -> GeocodeResponse:
        # 确定性伪坐标：以城市名哈希为基准，保证同名城市结果稳定
        base = sum(ord(c) for c in req.city) % 30 + 100.0
        return GeocodeResponse(lng=base, lat=25.0 + len(req.city) % 10, level="mock")

    async def poi_search(self, req: PoiSearchRequest) -> PoiSearchResponse:
        kinds = ["苍山景区", "洱海公园", "古城步行街", "崇圣寺三塔", "双廊小镇"]
        pois = [
            {
                "poi_id": f"mock-{req.city}-{i}",
                "name": f"{req.city}{name}",
                "category": "风景名胜" if i % 2 == 0 else "餐饮",
                "location": f"100.1{i}, 25.6{i}",
                "rating": round(4.0 + i * 0.2, 1),
                "tags": ["mock"],
            }
            for i, name in enumerate(kinds[: 25 if req.page >= 1 else 0])
        ]
        return PoiSearchResponse.model_validate({"pois": pois, "total": len(pois)})

    async def route_plan(self, req: RoutePlanRequest) -> RoutePlanResponse:
        n = max(1, len(req.waypoints) + 1)
        return RoutePlanResponse(
            distance_km=round(n * 12.5, 1),
            duration_min=round(n * 25.0, 0),
            steps_summary=[f"mock 路段 {i + 1}" for i in range(min(10, n))],
        )


class TTLCache:
    """极简进程内 TTL 缓存（POI/路线结果 24h，docs/07）。

    MVP 简化：单进程、无淘汰扫描（过期惰性失效）、无容量上限——
    存储层接线时迁到 Redis（已在 roadmap 登记）。
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires, value = item
        if time.monotonic() > expires:
            del self._store[key]
            return None
        return value

    def put(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic() + self._ttl, value)


class CachedMapProvider:
    """对 POI/路线做只读缓存的包装（geocode 也缓存，城市级地理编码极稳定）。"""

    def __init__(self, delegate: MapProvider, *, ttl_seconds: float = 24 * 3600) -> None:
        self._delegate = delegate
        self._cache = TTLCache(ttl_seconds)

    async def geocode(self, req: GeocodeRequest) -> GeocodeResponse:
        key = f"geo:{req.city}:{req.address}"
        if (hit := self._cache.get(key)) is None:
            hit = await self._delegate.geocode(req)
            self._cache.put(key, hit)
        return hit  # type: ignore[return-value]

    async def poi_search(self, req: PoiSearchRequest) -> PoiSearchResponse:
        key = f"poi:{req.model_dump_json()}"
        if (hit := self._cache.get(key)) is None:
            hit = await self._delegate.poi_search(req)
            self._cache.put(key, hit)
        return hit  # type: ignore[return-value]

    async def route_plan(self, req: RoutePlanRequest) -> RoutePlanResponse:
        key = f"route:{req.model_dump_json()}"
        if (hit := self._cache.get(key)) is None:
            hit = await self._delegate.route_plan(req)
            self._cache.put(key, hit)
        return hit  # type: ignore[return-value]
