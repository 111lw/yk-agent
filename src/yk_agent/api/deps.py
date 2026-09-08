"""FastAPI 依赖：路由统一经此取运行状态。

测试用 app.dependency_overrides[get_state] 注入 Mock 版 AppState。
"""

from __future__ import annotations

from fastapi import Request

from yk_agent.api.state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.app_state
