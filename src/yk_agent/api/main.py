"""应用入口：uvicorn yk_agent.api.main:app --reload（接口规范见 docs/08-api-spec.md）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from yk_agent.api.routes import chat, healthz, profile, trips
from yk_agent.api.state import build_default_state


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    state = await build_default_state()
    app.state.app_state = state
    yield
    if state.store is not None:
        await state.store.close()


app = FastAPI(title="yk-agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # MVP 开发全开；上线收敛
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(trips.router, prefix="/api")
app.include_router(healthz.router)  # /healthz 不带 /api（docs/08）
