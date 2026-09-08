"""map-mcp 工具契约：geocode / poi_search / route_plan（docs/07-mcp-tools.md §工具契约）。

坐标统一用 "lng,lat" 字符串（高德原生格式），避免float精度与序列化差异。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GeocodeRequest(BaseModel):
    city: str
    address: str


class GeocodeResponse(BaseModel):
    lng: float
    lat: float
    level: str | None = None  # 匹配精度（如 门牌号/道路/区县）


class Poi(BaseModel):
    poi_id: str
    name: str
    category: str | None = None  # 如 风景名胜/中餐厅
    location: str  # "lng,lat"
    address: str | None = None
    rating: float | None = None  # 0~5
    price_level: int | None = None  # 人均消费档位 1~5（高德 cost 换算）
    tags: list[str] = Field(default_factory=list)


class PoiSearchRequest(BaseModel):
    city: str
    keywords: str  # 检索词（如 "景点" / "云南菜"）
    category: str | None = None  # 高德分类码或分类名
    location: str | None = None  # "lng,lat" 中心点（配合 radius_km 做周边检索）
    radius_km: float = Field(default=5.0, gt=0, le=50)
    page: int = Field(default=1, ge=1)  # 每页固定 25，契约上限见 07 文档


class PoiSearchResponse(BaseModel):
    pois: list[Poi]
    total: int = 0


class RoutePlanRequest(BaseModel):
    origin: str  # "lng,lat"
    destination: str  # "lng,lat"
    waypoints: list[str] = Field(default_factory=list)  # 途经点（顺路规划核心）
    mode: Literal["driving", "walking", "transit"] = "driving"


class RoutePlanResponse(BaseModel):
    distance_km: float
    duration_min: float
    steps_summary: list[str] = Field(default_factory=list)  # 关键路段描述（≤10 条）
