# 07 MCP 工具设计

> MCP = 智能体与外部系统之间的标准化工具协议。MVP 采用「内部 tool 形式 + MCP 兼容封装」：工具逻辑写在 `mcp/`，先以函数形式被子智能体直接调用，同时保持 MCP server 可独立启动（V2 对外开放时零迁移）。

## 设计原则

1. **每个外部系统一个 MCP server**：map / weather / …，独立配置、独立鉴权、独立超时。
2. **工具契约先行**：先在本篇登记契约（下表），再写实现；入参出参用 pydantic 定义。
3. **超时与降级**：每个工具有独立 timeout；失败返回结构化错误（不是抛异常打断编排），由子智能体决定降级策略（见 03 文档护栏）。
4. **子智能体也可暴露为 MCP tool**：将 sub-agent 包装成 tool 提供给 Orchestrator，是"自主调用子智能体"的实现路径之一；MVP 用 LangGraph 原生 Send 派发，此路径 V2 开放给第三方时启用。

## 工具契约

### map-mcp（地图能力，MVP 依赖高德/百度开放平台，二选一，见 config）

| 工具 | 入参 | 出参 | 说明 |
|---|---|---|---|
| `geocode` | city, address | {lng, lat, level} | 地理编码 |
| `poi_search` | city, keywords, category?, location?, radius_km?, page | [{poi_id, name, category, location, rating, price_level, tags[]}] | POI 检索，分页 ≤25 |
| `route_plan` | origin, destination, waypoints[], mode(driving/walking/transit) | {distance_km, duration_min, steps_summary} | 多点顺路规划，route-agent 核心依赖 |

### weather-mcp（V2）

| 工具 | 入参 | 出参 |
|---|---|---|
| `forecast` | city, date_range | [{date, weather, temp_range, tips}] |

### 内部工具（非 MCP，但走同一 tool 契约注册）

| 工具 | 所在层 | 说明 |
|---|---|---|
| `kb_search` | knowledge/ | 向量+标签混合检索知识库（见 04 双通道） |
| `profile_lookup` | profile/ | 读当前用户画像切片（只读） |

## 模块划分（mcp/）

```
mcp/
├── contracts/       # 工具入参出参 pydantic 契约（唯一事实来源，本篇文档与其对齐）
├── map/             # map-mcp 实现：高德/百度 adapter + 缓存(POI 查询结果 Redis 缓存 24h)
├── weather/         # V2
└── base.py          # ToolResult / 工具注册器 / 超时与错误结构化封装
```

## 鉴权与配置

- 第三方 API key 全部走环境变量（`YK_AMAP_API_KEY` / `YK_BAIDU_MAP_API_KEY` …，统一 YK_ 前缀），见 02 文档配置管理。
- API key 出现在日志/trace 中必须脱敏。

## 新增工具流程

写契约（pydantic + 本文档登记）→ 实现 adapter → 接超时/缓存/脱敏 → 子智能体 Registry 中更新其 description 提及的新能力 → 单测（mock 第三方响应）。
