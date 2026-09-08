"""画像仓储：对上层只暴露接口，MVP 提供内存实现；PG 实现接入后替换。

设计约束（docs/02-architecture.md）：agents/core 不直接依赖存储实现，经本接口访问。
"""

from __future__ import annotations

from typing import Protocol

from yk_agent.profile.models import UserProfile


class ProfileRepository(Protocol):
    async def get(self, user_id: str) -> UserProfile: ...
    async def save(self, profile: UserProfile) -> None: ...


class InMemoryProfileRepository:
    """MVP 内存实现：进程生命周期内有效。PG 实现见 roadmap V2 前的存储接线步骤。"""

    def __init__(self) -> None:
        self._profiles: dict[str, UserProfile] = {}

    async def get(self, user_id: str) -> UserProfile:
        return self._profiles.get(user_id) or UserProfile(user_id=user_id)

    async def save(self, profile: UserProfile) -> None:
        self._profiles[profile.user_id] = profile
