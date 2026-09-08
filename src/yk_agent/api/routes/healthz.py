"""健康检查：DB/Redis/LLM 连通性摘要（docs/08-api-spec.md）。"""

from fastapi import APIRouter, Depends

from yk_agent.api.deps import get_state
from yk_agent.api.state import AppState

router = APIRouter()


@router.get("/healthz")
async def healthz(state: AppState = Depends(get_state)) -> dict:
    """MVP 检查 LLM provider 配置可用性 + 存储计数。"""
    try:
        from yk_agent.llm.factory import ProviderNotConfigured, get_provider

        try:
            get_provider()  # 触发配置检查，不发起实际调用
            llm_ok = True
        except ProviderNotConfigured:
            llm_ok = False
    except Exception:  # noqa: BLE001
        llm_ok = False
    counts = await state.counts()
    return {"status": "ok", "llm": llm_ok, **counts}
