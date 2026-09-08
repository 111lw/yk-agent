"""画像摘要生成：把画像压缩成注入 prompt 的短文本（token 预算友好）。

可解释推荐的地基：回答中引用的画像依据必须来自这里的真实内容，禁止编造。
"""

from __future__ import annotations

from yk_agent.profile.models import UserProfile

_DIMENSION_LABEL = {
    "pace": "节奏",
    "budget": "预算",
    "stay": "住宿",
    "food": "饮食",
    "transport": "交通",
    "interest": "兴趣",
    "companion": "同行",
}

_SENTIMENT_LABEL = {"like": "喜欢", "dislike": "不喜欢", "neutral": "中性"}


def summarize_profile(profile: UserProfile, *, max_preferences: int = 8) -> str:
    """生成画像摘要。按 |weight| 取 top-N 偏好，无画像时返回提示语。"""
    if not profile.persona_types and not profile.preferences:
        return "（该用户暂无画像，回答不要引用任何画像依据）"

    lines: list[str] = []
    if profile.persona_types:
        lines.append(f"旅行人格：{'、'.join(profile.persona_types)}")
    if profile.traits:
        traits = "、".join(f"{k}={v:.1f}" for k, v in profile.traits.items())
        lines.append(f"性格倾向：{traits}")

    top = sorted(profile.preferences, key=lambda p: abs(p.weight), reverse=True)[:max_preferences]
    for p in top:
        label = _DIMENSION_LABEL.get(p.dimension, p.dimension)
        sentiment = _SENTIMENT_LABEL[p.sentiment]
        lines.append(f"{label}·{sentiment} {p.value}（强度 {abs(p.weight):.1f}）")

    return "\n".join(lines)
