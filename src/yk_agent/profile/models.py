"""画像数据模型：三层画像（L1 静态人格 / L2 动态偏好）。

设计文档：docs/04-user-profile.md。维度与枚举值变更必须同步该文档。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# L1 旅行人格（8 类，最多 2 主类型；只影响表述与候选倾向，禁止作为硬过滤）
PersonaType = Literal[
    "探险型",
    "度假躺平型",
    "文化历史型",
    "美食型",
    "亲子型",
    "社交型",
    "自然风光型",
    "都市潮流型",
]

# L2 偏好维度
PreferenceDimension = Literal[
    "pace",  # 节奏
    "budget",  # 预算
    "stay",  # 住宿
    "food",  # 饮食
    "transport",  # 交通
    "interest",  # 兴趣点
    "companion",  # 同行人
]

Sentiment = Literal["like", "dislike", "neutral"]

# Big Five 简化维度的合法键（分值 0~1，允许缺省）
TRAIT_KEYS = {"openness", "conscientiousness", "extraversion", "agreeableness", "stability"}


class Preference(BaseModel):
    """一条结构化偏好。weight 与 sentiment 联动：like 为正、dislike 为负。"""

    dimension: PreferenceDimension
    value: str  # 规范化值（抽取器统一转小写英文规范词，如 hiking / spicy_food）
    sentiment: Sentiment = "neutral"
    weight: float = 0.0  # -1.0 ~ 1.0
    source: str  # 证据来源，可追溯（如 chat:msg-12 / feedback:trip-9）
    expires_at: datetime | None = None  # 时点性偏好（如"十一期间"）
    updated_at: datetime = Field(default_factory=datetime.now)

    @field_validator("weight")
    @classmethod
    def _clamp_weight(cls, v: float) -> float:
        return max(-1.0, min(1.0, v))


class UserProfile(BaseModel):
    """一个用户的完整画像（L1 + L2；L3 行为反馈在 feedback_events，不进本模型）。"""

    user_id: str
    persona_types: list[PersonaType] = Field(default_factory=list)  # 最多 2 个
    traits: dict[str, float] = Field(default_factory=dict)
    preferences: list[Preference] = Field(default_factory=list)

    @field_validator("persona_types")
    @classmethod
    def _cap_persona(cls, v: list) -> list:
        if len(v) > 2:
            raise ValueError(f"旅行人格最多 2 个，收到 {len(v)} 个: {v}")
        if len(v) != len(set(v)):
            raise ValueError(f"旅行人格重复: {v}")
        return v

    @field_validator("traits")
    @classmethod
    def _check_traits(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = set(v) - TRAIT_KEYS
        if unknown:
            raise ValueError(f"未知的人格维度: {sorted(unknown)}，合法键: {sorted(TRAIT_KEYS)}")
        for k, score in v.items():
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"人格分值须在 0~1: {k}={score}")
        return v
