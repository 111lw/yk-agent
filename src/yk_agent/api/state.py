"""API 层状态：provider / registry / graph / 存储（SQLite）/ 内存会话缓存。

存储（docs/decisions/ADR-002-sqlite.md）：传入 store 时全部持久化走 SQLite；
store 为 None（纯测试场景）回落内存实现。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from yk_agent.agents.bootstrap import build_default_registry
from yk_agent.core.graph import build_graph
from yk_agent.knowledge.retriever import KbRetriever
from yk_agent.llm.provider import LLMProvider
from yk_agent.mcp.map.provider import MapProvider
from yk_agent.profile.models import UserProfile
from yk_agent.profile.repository import InMemoryProfileRepository, ProfileRepository
from yk_agent.skills.loader import load_skill
from yk_agent.storage.sqlite import SqliteProfileRepository, SqliteStore


@dataclass
class ChatSession:
    session_id: str
    user_id: str
    history: list[dict[str, str]] = field(default_factory=list)  # [{role, content}]


@dataclass
class TripRecord:
    trip_id: str
    user_id: str
    session_id: str
    final_answer: str
    findings: dict[str, Any]  # 各子智能体产出快照
    profile_snapshot: dict[str, Any] = field(default_factory=dict)
    status: str = "draft"  # draft/accepted/modified/rejected
    feedback: list[dict[str, Any]] = field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        return {
            "trip_id": self.trip_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "final_answer": self.final_answer,
            "findings": self.findings,
            "profile_snapshot": self.profile_snapshot,
            "status": self.status,
        }


class AppState:
    """FastAPI app 持有的运行期单例（lifespan 初始化，测试可覆写注入 Mock）。"""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        map_provider: MapProvider,
        store: SqliteStore | None = None,
        profile_repo: ProfileRepository | None = None,
    ) -> None:
        self.provider = provider
        self.map_provider = map_provider
        self.store = store
        if store is not None and profile_repo is None:
            profile_repo = SqliteProfileRepository(store)
        self.profile_repo = profile_repo or InMemoryProfileRepository()
        # 知识库检索器：无持久化 store 时不启用（纯测试场景）
        self.kb = KbRetriever(store, provider) if store is not None else None
        self.registry = build_default_registry(self.map_provider, kb=self.kb)
        self.graph: CompiledStateGraph = build_graph(
            self.registry, self.provider, skills=[load_skill("trip-planner")]
        )
        self.sessions: dict[str, ChatSession] = {}  # 内存热缓存（持久化在 store）
        self._memory_trips: dict[str, TripRecord] = {}  # 仅 store=None 的测试场景

    async def get_or_create_session(self, user_id: str, session_id: str | None) -> ChatSession:
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        new_id = session_id or uuid.uuid4().hex
        sess = ChatSession(session_id=new_id, user_id=user_id)
        self.sessions[new_id] = sess
        if self.store is not None:
            await self.store.ensure_session(new_id, user_id)
        return sess

    async def save_trip(self, record: TripRecord) -> None:
        if self.store is not None:
            await self.store.save_trip(record.to_row())
        else:
            self._memory_trips[record.trip_id] = record

    async def list_trips(self, user_id: str) -> list[dict[str, Any]]:
        if self.store is not None:
            return await self.store.list_trips(user_id)
        return [
            {"trip_id": r.trip_id, "status": r.status, "answer_head": r.final_answer[:100]}
            for r in self._memory_trips.values()
            if r.user_id == user_id
        ]

    async def get_trip(self, trip_id: str, user_id: str) -> dict[str, Any] | None:
        if self.store is not None:
            return await self.store.get_trip(trip_id, user_id)
        record = self._memory_trips.get(trip_id)
        if record is None or record.user_id != user_id:
            return None
        return {
            "trip_id": record.trip_id,
            "session_id": record.session_id,
            "status": record.status,
            "final_answer": record.final_answer,
            "findings": record.findings,
            "profile_snapshot": record.profile_snapshot,
            "feedback": record.feedback,
        }

    async def update_trip_status(
        self, trip_id: str, user_id: str, status: str, feedback: dict[str, Any]
    ) -> bool:
        if self.store is not None:
            return await self.store.update_trip_status(trip_id, user_id, status, feedback)
        record = self._memory_trips.get(trip_id)
        if record is None or record.user_id != user_id:
            return False
        record.status = status
        record.feedback.append(feedback)
        return True

    async def write_trace(
        self,
        *,
        session_id: str,
        user_id: str,
        plan_snapshot: list,
        dispatches: list,
        critic_verdict: dict | None,
        total_tokens: int,
    ) -> None:
        """编排 trace 落库（docs/03 §可观测性硬要求）；无 store 时静默跳过。"""
        if self.store is None:
            return
        await self.store.write_trace(
            session_id=session_id,
            user_id=user_id,
            plan_snapshot=plan_snapshot,
            dispatches=dispatches,
            critic_verdict=critic_verdict,
            total_tokens=total_tokens,
        )

    async def counts(self) -> dict[str, int]:
        """健康检查用计数。"""
        if self.store is not None:
            return await self.store.counts()
        return {"sessions": len(self.sessions), "trips": len(self._memory_trips)}


async def build_default_state() -> AppState:
    """从全局配置构建运行状态（生产/开发入口）。测试用 AppState 构造器直接注入 Mock。"""
    from yk_agent.config import settings
    from yk_agent.llm.factory import get_provider
    from yk_agent.mcp.map.factory import get_map_provider
    from yk_agent.storage.sqlite import SqliteStore, sqlite_path_from_url

    store: SqliteStore | None = None
    if settings.database_url.startswith("sqlite:///"):
        store = SqliteStore(sqlite_path_from_url(settings.database_url))
        await store.connect()
    else:
        import logging

        logging.getLogger(__name__).warning(
            "YK_DATABASE_URL 非 sqlite://（当前仅支持 SQLite，见 ADR-002），回落内存存储"
        )

    return AppState(provider=get_provider(), map_provider=get_map_provider(), store=store)


def profile_to_dict(profile: UserProfile) -> dict[str, Any]:
    """画像 → 编排层/JSON 序列化形式（注入 TripState / trips 快照）。"""
    return profile.model_dump(mode="json")
