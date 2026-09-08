"""map provider 工厂：按配置选择真实/模拟实现，并包缓存。"""

from __future__ import annotations

import logging

from yk_agent.config import settings
from yk_agent.mcp.map.amap import AmapProvider
from yk_agent.mcp.map.provider import CachedMapProvider, MapProvider, MockMapProvider

logger = logging.getLogger(__name__)


def get_map_provider() -> MapProvider:
    """有高德 key 用真实 provider，否则回落 Mock（离线开发/测试），只告警不阻断。"""
    if settings.amap_api_key:
        return CachedMapProvider(AmapProvider(api_key=settings.amap_api_key))
    logger.warning("未配置 YK_AMAP_API_KEY，地图工具使用 MockMapProvider（数据为假）")
    return CachedMapProvider(MockMapProvider())
