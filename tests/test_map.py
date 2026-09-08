"""map 工具层单测：契约 / Mock provider / TTL 缓存 / run_tool 错误收敛。"""

import asyncio

import httpx
import pytest
from pydantic import ValidationError

from yk_agent.mcp.base import ToolResult, run_tool
from yk_agent.mcp.contracts.map import (
    GeocodeRequest,
    PoiSearchRequest,
    RoutePlanRequest,
)
from yk_agent.mcp.map.amap import AmapError, AmapProvider
from yk_agent.mcp.map.factory import get_map_provider
from yk_agent.mcp.map.provider import CachedMapProvider, MockMapProvider, TTLCache

# ---------- 契约 ----------


def test_poi_search_request_defaults():
    req = PoiSearchRequest(city="大理", keywords="景点")
    assert req.radius_km == 5.0 and req.page == 1
    with pytest.raises(ValueError):
        PoiSearchRequest(city="大理", keywords="x", page=0)  # 页码必须 ≥1
    with pytest.raises(ValueError):
        PoiSearchRequest(city="大理", keywords="x", radius_km=100)  # 半径上限 50km


def test_route_mode_enum():
    with pytest.raises(ValueError):
        RoutePlanRequest(origin="1,2", destination="3,4", mode="swimming")


# ---------- Mock provider ----------


async def test_mock_provider_deterministic():
    mock = MockMapProvider()
    r1 = await mock.poi_search(PoiSearchRequest(city="大理", keywords="景点"))
    r2 = await mock.poi_search(PoiSearchRequest(city="大理", keywords="景点"))
    assert r1.model_dump() == r2.model_dump()
    assert len(r1.pois) > 0 and r1.pois[0].name.startswith("大理")
    route = await mock.route_plan(
        RoutePlanRequest(origin="1,1", destination="2,2", waypoints=["3,3"])
    )
    assert route.distance_km == 25.0  # 2 段 × 12.5


# ---------- TTL 缓存 ----------


async def test_cached_provider_hits_cache():
    class CountingProvider(MockMapProvider):
        def __init__(self):
            self.calls = 0

        async def poi_search(self, req):
            self.calls += 1
            return await super().poi_search(req)

    inner = CountingProvider()
    cached = CachedMapProvider(inner, ttl_seconds=60)
    req = PoiSearchRequest(city="大理", keywords="景点")
    await cached.poi_search(req)
    await cached.poi_search(req)
    assert inner.calls == 1  # 第二次命中缓存


def test_ttl_cache_expiry():
    cache = TTLCache(ttl_seconds=-1)  # 立即过期
    cache.put("k", "v")
    assert cache.get("k") is None


# ---------- run_tool 错误收敛 ----------


async def test_run_tool_converges_exception_to_failure():
    async def boom() -> None:
        raise RuntimeError("第三方挂了")

    result = await run_tool("poi_search", boom)
    assert result.ok is False
    assert "RuntimeError" in result.error
    assert result.data is None


async def test_run_tool_timeout():
    async def slow() -> None:
        await asyncio.sleep(1)

    result = await run_tool("slow_tool", slow, timeout=0.01)
    assert result.ok is False and "超时" in result.error


# ---------- 工厂 ----------


def test_factory_returns_cached_provider():
    provider = get_map_provider()
    assert isinstance(provider, CachedMapProvider)


# ---------- 高德 adapter（mock HTTP，验证响应解析与错误收敛）----------


def _amap_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


async def test_amap_poi_search_parses_response():
    transport = httpx.MockTransport(
        lambda req: _amap_response(
            {
                "status": "1",
                "count": "2",
                "pois": [
                    {
                        "id": "B001",
                        "name": "崇圣寺三塔",
                        "type": "风景名胜;寺庙",
                        "location": "100.1,25.7",
                        "address": "大理镇",
                        "biz_ext": {"rating": "4.8", "cost": "75"},
                    },
                    {"id": "B002", "name": "无附加字段POI", "location": "100.2,25.8"},
                ],
            }
        )
    )
    provider = AmapProvider(api_key="test", client=httpx.AsyncClient(transport=transport))
    resp = await provider.poi_search(PoiSearchRequest(city="大理", keywords="景点"))
    assert resp.total == 2
    assert resp.pois[0].rating == 4.8 and resp.pois[0].price_level == 75
    assert resp.pois[0].category == "风景名胜"  # 只取一级分类
    assert resp.pois[1].rating is None  # 缺失字段 → None，不编造


async def test_amap_status_zero_raises():
    payload = {"status": "0", "infocode": "10001", "info": "INVALID_USER_KEY"}
    transport = httpx.MockTransport(lambda req: _amap_response(payload))
    provider = AmapProvider(api_key="bad", client=httpx.AsyncClient(transport=transport))
    with pytest.raises(AmapError, match="INVALID_USER_KEY"):
        await provider.geocode(GeocodeRequest(city="大理", address="古城"))


async def test_amap_transit_structural_degradation():
    transport = httpx.MockTransport(lambda req: _amap_response({}))
    provider = AmapProvider(api_key="test", client=httpx.AsyncClient(transport=transport))
    with pytest.raises(AmapError, match="transit"):
        await provider.route_plan(RoutePlanRequest(origin="1,1", destination="2,2", mode="transit"))


def test_tool_result_invariants():
    # 契约联动：ok=False 必须带 error（pydantic ValidationError）
    with pytest.raises(ValidationError):
        ToolResult(ok=False, error=None)
    with pytest.raises(ValidationError):
        ToolResult(ok=True, data=None)
