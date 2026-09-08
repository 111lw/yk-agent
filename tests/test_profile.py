"""画像模块单测：模型校验 / 合并规则 / 抽取器（MockLLM）/ 摘要 / 仓储。"""

import pytest
from pydantic import ValidationError

from yk_agent.llm.mock import MockLLMProvider
from yk_agent.profile.extractor import extract_preferences
from yk_agent.profile.merger import merge_persona, merge_preference, merge_profile
from yk_agent.profile.models import Preference, UserProfile
from yk_agent.profile.repository import InMemoryProfileRepository
from yk_agent.profile.summarizer import summarize_profile

SRC = "chat:msg-1"


def _pref(dim="interest", value="hiking", sentiment="like", weight=0.5, source=SRC) -> Preference:
    return Preference(dimension=dim, value=value, sentiment=sentiment, weight=weight, source=source)  # type: ignore[arg-type]


# ---------- models ----------


def test_persona_max_two_and_unique():
    with pytest.raises(ValidationError, match="最多 2 个"):
        UserProfile(user_id="u", persona_types=["美食型", "亲子型", "探险型"])
    with pytest.raises(ValidationError, match="重复"):
        UserProfile(user_id="u", persona_types=["美食型", "美食型"])


def test_trait_validation():
    with pytest.raises(ValidationError, match="未知的人格维度"):
        UserProfile(user_id="u", traits={"mood": 0.5})
    with pytest.raises(ValidationError, match="0~1"):
        UserProfile(user_id="u", traits={"openness": 1.5})


def test_weight_clamped_in_model():
    assert _pref(weight=2.0).weight == 1.0
    assert _pref(weight=-3.0).weight == -1.0


# ---------- merger（docs/04 合并规则的核心验证）----------


def test_merge_same_direction_accumulates_and_clamps():
    prefs = merge_preference([_pref(weight=0.6)], _pref(weight=0.6))
    assert prefs[0].weight == 1.0  # 0.6+0.6 → 截断 1.0
    assert prefs[0].source == SRC  # 刷新证据来源
    assert len(prefs) == 1  # 不新增条目


def test_merge_contradiction_halves_then_accumulates():
    # 先说想吃辣(+0.8)，后说不吃辣(-0.6)：新值覆盖，weight 减半再累加
    spicy = _pref(dim="food", value="spicy", weight=0.8)
    no_spicy = _pref(dim="food", value="spicy", sentiment="dislike", weight=-0.6)
    prefs = merge_preference([spicy], no_spicy)
    assert prefs[0].sentiment == "dislike"
    assert prefs[0].weight == pytest.approx(0.8 * 0.5 - 0.6)  # -0.2


def test_merge_new_value_appends():
    prefs = merge_preference([_pref()], _pref(value="museum", weight=0.7))
    assert len(prefs) == 2
    assert {p.value for p in prefs} == {"hiking", "museum"}


def test_merge_does_not_mutate_input():
    original = [_pref()]
    merge_preference(original, _pref(value="beach"))
    assert len(original) == 1


def test_merge_persona_fifo():
    p = UserProfile(user_id="u", persona_types=["美食型", "亲子型"])
    p = merge_persona(p, ["探险型"])
    assert p.persona_types == ["亲子型", "探险型"]  # 最旧的美食型被淘汰


def test_merge_profile_end_to_end():
    profile = UserProfile(user_id="u")
    profile = merge_profile(
        profile,
        persona_updates=["美食型"],
        preference_deltas=[_pref(), _pref(dim="pace", value="slow", weight=0.4)],
    )
    assert profile.persona_types == ["美食型"]
    assert len(profile.preferences) == 2


# ---------- extractor ----------


async def test_extractor_dislike_becomes_negative_weight():
    delta = '{"dimension": "interest", "value": "Hiking", "sentiment": "dislike", "intensity": 0.8}'
    mock = MockLLMProvider(
        ['{"persona_updates": ["自然风光型"], "preference_deltas": [' + delta + "]}"]
    )
    result = await extract_preferences(mock, dialogue="我不想爬山", source=SRC)
    assert result.persona_updates == ["自然风光型"]
    pref = result.preference_deltas[0].to_preference(SRC)
    assert pref.value == "hiking"  # 规范化：小写
    assert pref.weight == -0.8  # dislike → 负号
    assert pref.dimension == "interest"


async def test_extractor_empty_delta_when_no_preference():
    mock = MockLLMProvider(['{"persona_updates": [], "preference_deltas": []}'])
    result = await extract_preferences(mock, dialogue="今天天气不错", source=SRC)
    assert result.preference_deltas == []


# ---------- summarizer ----------


def test_summarizer_lists_persona_and_top_preferences():
    profile = UserProfile(
        user_id="u",
        persona_types=["美食型"],
        preferences=[_pref(weight=0.9), _pref(dim="pace", value="slow", weight=0.3)],
    )
    text = summarize_profile(profile)
    assert "美食型" in text
    assert "hiking" in text and "0.9" in text  # 按 |weight| 排序在前


def test_summarizer_empty_profile():
    assert "暂无画像" in summarize_profile(UserProfile(user_id="u"))


# ---------- repository ----------


async def test_in_memory_repository_roundtrip():
    repo = InMemoryProfileRepository()
    assert (await repo.get("u1")).preferences == []  # 未建画像返回空画像而非报错
    profile = merge_profile(await repo.get("u1"), persona_updates=[], preference_deltas=[_pref()])
    await repo.save(profile)
    assert (await repo.get("u1")).preferences[0].value == "hiking"
