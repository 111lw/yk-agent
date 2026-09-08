"""偏好抽取器：从对话中抽取偏好增量（LLM 结构化输出）。

每轮对话后调用，输出可空的增量列表 → merger.merge_profile 合入画像。
抽取失败不影响主流程（上层捕获后降级为不更新画像），但记日志。
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from yk_agent.llm.json_utils import chat_validated
from yk_agent.llm.models import ChatMessage
from yk_agent.llm.provider import LLMProvider
from yk_agent.profile.models import Preference

logger = logging.getLogger(__name__)

# value 规范词表（英文小写下划线）。开放值允许抽取器自造，规范词优先。
_CANONICAL_VALUES = {
    "pace": "slow / fast / balanced",
    "budget": "low / mid / high（或具体区间如 3000-5000cny）",
    "stay": "budget_hostel / comfort_hotel / resort / boutique / homestay",
    "food": "spicy / light / street_food / fine_dining / vegetarian / no_seafood",
    "transport": "flight / train / self_driving / public_transit",
    "interest": "hiking / museum / photography / nightlife / shopping / beach / history / wildlife",
    "companion": "solo / couple / family_with_kids / friends / parents",
}

_EXTRACT_SYSTEM = """你是用户画像抽取器。从旅游对话中抽取用户的偏好增量。

可抽取的维度与参考值：
{canonical}

规则：
1. 只抽取用户明确表达的偏好，不要推测。没有新偏好时返回空列表。
2. value 用参考值中的规范词（小写英文）；确实没有合适规范词时可用自造英文小写下划线词。
3. intensity 表达偏好强度 0.1~1.0（"不喜欢爬山"≈0.8，"还行"≈0.3）。
4. sentiment: like / dislike / neutral。dislike 的 weight 由 intensity 转负，勿填负数。
5. 时间限定偏好（如"十一期间"）填写 expires_at 描述；无则留空。
6. persona_updates 仅在对话能明确判断旅行人格类型时填写（可多选，最多推断 2 个）：
   探险型/度假躺平型/文化历史型/美食型/亲子型/社交型/自然风光型/都市潮流型
只输出 JSON。"""


class PreferenceDelta(BaseModel):
    """抽取器输出的一条偏好增量（intensity 恒为正，符号由 sentiment 决定）。"""

    dimension: str  # 校验放这里宽松、落到 Preference 再严格——避免 LLM 输出直接炸掉整个抽取
    value: str
    sentiment: Literal["like", "dislike", "neutral"] = "neutral"
    intensity: float = Field(default=0.5, ge=0.1, le=1.0)
    evidence: str = ""  # 用户原话片段
    expires_at: str | None = None

    def to_preference(self, source: str) -> Preference:
        weight = self.intensity if self.sentiment != "dislike" else -self.intensity
        return Preference(
            dimension=self.dimension,  # type: ignore[arg-type] — dimension 非法时由 Preference 校验抛出
            value=self.value.strip().lower().replace(" ", "_"),
            sentiment=self.sentiment,
            weight=weight,
            source=source,
        )


class ExtractionResult(BaseModel):
    """一次抽取的结构化输出。"""

    persona_updates: list[str] = Field(default_factory=list, max_length=2)
    preference_deltas: list[PreferenceDelta] = Field(default_factory=list)


async def extract_preferences(
    provider: LLMProvider,
    *,
    dialogue: str,
    profile_summary: str = "（暂无画像）",
    source: str,
) -> ExtractionResult:
    """从本轮对话抽取偏好增量。dialogue 为本轮（或最近几轮）对话文本。"""
    messages = [
        ChatMessage(role="system", content=_EXTRACT_SYSTEM.format(canonical=_CANONICAL_VALUES)),
        ChatMessage(
            role="user",
            content=f"现有画像摘要：{profile_summary}\n\n本轮对话：\n{dialogue}",
        ),
    ]
    result = await chat_validated(provider, messages, ExtractionResult)
    logger.info(
        "偏好抽取: %d 条增量, %d 个人格更新",
        len(result.preference_deltas),
        len(result.persona_updates),
    )
    return result
