"""画像接口：GET/PUT /api/profile（docs/08-api-spec.md）。

PUT 语义：用户手动修正视为强信号——persona_types 直接覆盖；preferences 走
merge_preference 合并（矛盾按抽取器同款规则收敛），不是整体替换。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from yk_agent.api.deps import get_state
from yk_agent.api.state import AppState
from yk_agent.profile.merger import merge_preference
from yk_agent.profile.models import Preference, UserProfile
from yk_agent.profile.summarizer import summarize_profile

router = APIRouter(prefix="/profile")


class ProfileUpdate(BaseModel):
    persona_types: list[str] | None = None
    preferences: list[Preference] | None = None


@router.get("")
async def get_profile(state: AppState = Depends(get_state), x_user_id: str = Header(...)) -> dict:
    profile = await state.profile_repo.get(x_user_id)
    return {"profile": profile.model_dump(mode="json"), "summary": summarize_profile(profile)}


@router.put("")
async def put_profile(
    update: ProfileUpdate,
    state: AppState = Depends(get_state),
    x_user_id: str = Header(...),
) -> dict:
    profile = await state.profile_repo.get(x_user_id)
    if update.persona_types is not None:
        # 重建实例以复用 persona 校验（最多 2 个、去重、枚举合法性）
        profile = UserProfile(
            user_id=profile.user_id,
            persona_types=update.persona_types,  # type: ignore[arg-type]
            traits=profile.traits,
            preferences=profile.preferences,
        )
    if update.preferences:
        merged = profile.preferences
        for delta in update.preferences:
            merged = merge_preference(merged, delta)
        profile = profile.model_copy(update={"preferences": merged})
    await state.profile_repo.save(profile)
    return {"profile": profile.model_dump(mode="json"), "summary": summarize_profile(profile)}
