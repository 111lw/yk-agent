"""API 层状态：provider / registry / graph / 内存会话与攻略 / 画像仓储。

MVP 全部内存：进程重启即丢失；持久化随存储接线步骤一起落地（roadmap V2 前）。
接口契约见 docs/08-api-spec.md。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langgraph.graph.state import CompiledStateGraph

from yk_agent.agents.bootstrap import build_default_registry
from yk_agent.core.graph import build_graph
from yk_agent.llm.factory import get_provider
from yk_agent.llm.provider import LLMProvider
from yk_agent.mcp.map.factory import get_map_provider
from yk_agent.mcp.map.provider import MapProvider
from yk_agent.profile.models import UserProfile
from yk_agent.profile.repository import InMemoryProfileRepository, ProfileRepository
from yk_agent.skills.loader import load_skill

if TYPE_CHECKING:
    from langgraph.graph import StateGraph  # noqa: F401


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


class AppState:
    """FastAPI app 持有的运行期单例（lifespan 初始化，测试可覆写）。"""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        map_provider: MapProvider,
        profile_repo: ProfileRepository | None = None,
    ) -> None:
        self.provider = provider
        self.map_provider = map_provider
        self.profile_repo = profile_repo or InMemoryProfileRepository()
        self.registry = build_default_registry(self.map_provider)
        self.graph: CompiledStateGraph = build_graph(
            self.registry, self.provider, skills=[load_skill("trip-planner")]
        )
        self.sessions: dict[str, ChatSession] = {}
        self.trips: dict[str, TripRecord] = {}

    def get_or_create_session(self, user_id: str, session_id: str | None) -> ChatSession:
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        new_id = session_id or uuid.uuid4().hex
        sess = ChatSession(session_id=new_id, user_id=user_id)
        self.sessions[new_id] = sess
        return sess

    def save_trip(self, record: TripRecord) -> None:
        self.trips[record.trip_id] = record


def build_default_state() -> AppState:
    """从全局配置构建运行状态（生产/开发入口）。测试中用 AppState 构造器直接注入 Mock。"""
    return AppState(provider=get_provider(), map_provider=get_map_provider())


def profile_to_dict(profile: UserProfile) -> dict[str, Any]:
    """画像 → 编排层/JSON 序列化形式（注入 TripState / trips 快照）。"""
    return profile.model_dump(mode="json")
