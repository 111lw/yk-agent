"""偏好增量合并规则（纯函数，无 LLM/IO，重点单测对象）。

docs/04-user-profile.md §偏好抽取器：
- 幂等合并：同 (dimension, value) 再次出现 → weight 累加并截断 ±1.0，刷新 source；
- 矛盾值（sentiment 相反）→ 以新值覆盖，weight 减半再累加（先说想吃辣后说不吃辣）；
- 人格类型：新类型追加，总数超过 2 时按出现顺序淘汰最旧的（FIFO）。
"""

from __future__ import annotations

from yk_agent.profile.models import Preference, UserProfile


def merge_preference(preferences: list[Preference], delta: Preference, /) -> list[Preference]:
    """把一条新偏好合入列表，返回新列表（不修改入参）。"""
    for i, p in enumerate(preferences):
        if p.dimension != delta.dimension or p.value != delta.value:
            continue

        if p.sentiment == delta.sentiment or "neutral" in (p.sentiment, delta.sentiment):
            # 同向（或任一方 neutral）：weight 累加并截断到 ±1.0
            weight = max(-1.0, min(1.0, p.weight + delta.weight))
            sentiment = delta.sentiment if delta.sentiment != "neutral" else p.sentiment
        else:
            # 矛盾（like vs dislike）：以新值覆盖，weight 减半再累加
            weight = max(-1.0, min(1.0, p.weight * 0.5 + delta.weight))
            sentiment = delta.sentiment

        replacement = p.model_copy(
            update={
                "sentiment": sentiment,
                "weight": weight,
                "source": delta.source,
                "expires_at": delta.expires_at,
                "updated_at": delta.updated_at,
            }
        )
        return preferences[:i] + [replacement] + preferences[i + 1 :]

    return [*preferences, delta]


def merge_persona(profile: UserProfile, new_types: list[str]) -> UserProfile:
    """追加新人格类型；超过 2 个时按出现顺序淘汰最旧的（FIFO）。"""
    current = list(profile.persona_types)
    for t in new_types:
        if t not in current:
            current.append(t)  # type: ignore[arg-type] — 非法值由 UserProfile 校验兜底
    return profile.model_copy(update={"persona_types": current[-2:]})


def merge_profile(
    profile: UserProfile,
    *,
    persona_updates: list[str],
    preference_deltas: list[Preference],
) -> UserProfile:
    """抽取结果合入画像：人格追加 + 偏好逐条合并。"""
    if persona_updates:
        profile = merge_persona(profile, persona_updates)
    for delta in preference_deltas:
        profile = profile.model_copy(
            update={"preferences": merge_preference(profile.preferences, delta)}
        )
    return profile
