"""子智能体公共基座：统一派发载荷模型。

graph 派发 payload 固定含 agent/instruction/user_message/user_profile/upstream
（见 core/graph.py route_from_orchestrator），各子智能体 input_schema 继承本模型。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")  # 派发载荷的公共键之外的字段忽略

    agent: str
    instruction: str  # Orchestrator 写的具体任务指令（约定携带 城市=/天数=/预算= 等结构化片段）
    user_message: str = ""
    user_profile: dict[str, Any] = {}  # 画像切片：preferences 列表等（见 docs/04）
    upstream: dict[str, Any] = {}  # 依赖子智能体的 AgentFinding.model_dump()


def parse_slot(instruction: str, key: str, *, stop_at_comma: bool = True) -> str | None:
    """从 instruction 提取 "key=值" 结构化片段（中文冒号/等号均支持）。

    stop_at_comma=False 用于"关键词=a,b,c"这类值内含逗号的片段（取到空白为止）。
    """
    import re

    value_pattern = r"[^\s；;，,]+" if stop_at_comma else r".+?(?=\s|$)"
    m = re.search(rf"{key}\s*[:：=]\s*({value_pattern})", instruction)
    return m.group(1).strip() if m else None
