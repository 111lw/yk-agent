"""SSE 事件模型与序列化（docs/08-api-spec.md §核心：对话 SSE 事件流）。"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel

EventName = Literal[
    "session",  # 首事件，必发
    "plan_update",  # 计划生成/修订
    "agent_start",  # 子智能体派发开始
    "agent_end",  # 子智能体派发结束
    "confirmation_request",  # 副作用动作等待确认（V2）
    "token",  # 最终回答流式 token
    "done",  # 正常结束
    "error",  # 错误终止
]


class SSEEvent(BaseModel):
    event: EventName
    data: dict[str, Any]

    def encode(self) -> dict[str, str]:
        return {"event": self.event, "data": json.dumps(self.data, ensure_ascii=False)}
