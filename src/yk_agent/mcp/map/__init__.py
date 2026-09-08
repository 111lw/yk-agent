"""map-mcp：地图能力（geocode / poi_search / route_plan）。

MVP 双实现：AmapProvider（真实高德 REST）+ MockMapProvider（离线开发/测试），
经 factory.get_map_provider() 按配置选择。契约见 mcp/contracts/map.py。
"""
