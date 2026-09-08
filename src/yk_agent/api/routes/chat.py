"""核心对话接口：POST /api/chat（SSE 流式，docs/08-api-spec.md §核心）。

MVP 简化（已登记 V2 清理）：
- responder 的最终回答整段作为单个 token 事件发出（graph 内 responder 为一次性
  LLM 调用，真流式需改造 provider 支持异步迭代，见 docs/02 §模型接入层）；
- 无 checkpoint（断线重连暂不恢复编排上下文）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from yk_agent.api.deps import get_state
from yk_agent.api.events import SSEEvent
from yk_agent.api.state import AppState, TripRecord, profile_to_dict
from yk_agent.core.state import TripState
from yk_agent.profile.extractor import extract_preferences
from yk_agent.profile.merger import merge_profile
from yk_agent.profile.summarizer import summarize_profile

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@router.post("/chat", response_model=None)  # SSE 流式响应不走 FastAPI response_model
async def chat(
    req: ChatRequest,
    state: AppState = Depends(get_state),
    x_user_id: str | None = Header(default=None),
) -> EventSourceResponse:
    user_id = x_user_id or f"anon-{uuid.uuid4().hex[:8]}"
    agent_nodes = {s.graph_node for s in state.registry.specs()}

    async def event_stream() -> AsyncIterator[dict[str, str]]:
        sess = state.get_or_create_session(user_id, req.session_id)
        yield SSEEvent(
            event="session", data={"session_id": sess.session_id, "user_id": user_id}
        ).encode()

        profile = await state.profile_repo.get(user_id)
        graph_state: TripState = {
            "session_id": sess.session_id,
            "user_id": user_id,
            "user_message": req.message,
            "user_profile": profile_to_dict(profile),
        }

        try:
            final_answer: str | None = None
            findings: dict[str, Any] = {}

            async for ev in state.graph.astream_events(graph_state, version="v2"):
                kind = ev.get("event")
                node = (ev.get("metadata") or {}).get("langgraph_node")
                out = (ev.get("data") or {}).get("output")
                if kind == "on_chain_stream" and node in agent_nodes:
                    # Send 派发的子智能体不发 on_chain_start，用 on_chain_stream 作为开始信号
                    yield SSEEvent(event="agent_start", data={"agent": node}).encode()
                    continue
                if not isinstance(out, dict):
                    # 路由函数（返回 Send 列表/字符串）等事件的 output 非 dict
                    continue
                if kind == "on_chain_end" and node in agent_nodes:
                    if out.get("findings"):
                        findings.update(out["findings"])
                    yield SSEEvent(event="agent_end", data={"agent": node, "status": "ok"}).encode()
                elif kind == "on_chain_end" and node == "orchestrator":
                    if out.get("plan"):
                        yield SSEEvent(event="plan_update", data={"tasks": out["plan"]}).encode()
                elif kind == "on_chain_end" and node == "responder":
                    final_answer = out.get("final_answer")
                    if final_answer:
                        yield SSEEvent(event="token", data={"text": final_answer}).encode()

            # —— 回写：攻略存档 + 偏好抽取 ——
            trip_id = None
            if final_answer and findings:
                trip_id = uuid.uuid4().hex
                state.save_trip(
                    TripRecord(
                        trip_id=trip_id,
                        user_id=user_id,
                        session_id=sess.session_id,
                        final_answer=final_answer,
                        findings=findings,
                        profile_snapshot=profile_to_dict(profile),
                    )
                )
            try:
                extraction = await extract_preferences(
                    state.provider,
                    dialogue=f"用户：{req.message}\n助手：{final_answer or ''}",
                    profile_summary=summarize_profile(profile),
                    source=f"chat:{sess.session_id}",
                )
                deltas = [
                    d.to_preference(f"chat:{sess.session_id}") for d in extraction.preference_deltas
                ]
                await state.profile_repo.save(
                    merge_profile(
                        profile,
                        persona_updates=extraction.persona_updates,
                        preference_deltas=deltas,
                    )
                )
            except Exception as e:  # noqa: BLE001 — 画像抽取失败不影响主回答
                logger.warning("画像抽取回写失败（降级跳过）: %s", e)

            sess.history.append({"role": "user", "content": req.message})
            sess.history.append({"role": "assistant", "content": final_answer or ""})

            yield SSEEvent(event="done", data={"trip_id": trip_id}).encode()
        except Exception as e:  # noqa: BLE001 — SSE 内错误必须以 error 事件收敛
            logger.exception("编排执行失败")
            yield SSEEvent(
                event="error", data={"code": "ORCHESTRATION_FAILED", "message": str(e)[:200]}
            ).encode()

    return EventSourceResponse(event_stream())
