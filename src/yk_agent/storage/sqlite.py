"""SQLite 存储实现：画像 / 会话消息 / 攻略 / 编排 trace。

设计说明（docs/05-data-model.md、docs/decisions/ADR-002-sqlite.md）：
- **全环境 SQLite**（零运维、单机部署）；schema 事实来源 = 本文件 _SCHEMA；
- JSON 列存 TEXT；无向量列（RAG 阶段以 JSON 存取向量 + 内存余弦计算）；
- 所有写操作经单连接串行执行（SQLite 单写者），WAL 模式提升读并发。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from yk_agent.profile.models import Preference, UserProfile

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    nickname    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id       TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    persona_types TEXT NOT NULL DEFAULT '[]',   -- JSON 数组
    traits        TEXT NOT NULL DEFAULT '{}',   -- JSON 对象
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_preferences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dimension   TEXT NOT NULL,
    value       TEXT NOT NULL,
    sentiment   TEXT NOT NULL DEFAULT 'neutral',
    weight      REAL NOT NULL DEFAULT 0,
    source      TEXT NOT NULL,
    expires_at  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, dimension, value)
);
CREATE INDEX IF NOT EXISTS idx_pref_user ON user_preferences (user_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON chat_messages (session_id, created_at);

CREATE TABLE IF NOT EXISTS trips (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id       TEXT,
    final_answer     TEXT NOT NULL,
    findings         TEXT NOT NULL DEFAULT '{}',         -- JSON
    profile_snapshot TEXT NOT NULL DEFAULT '{}',         -- JSON
    status           TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'accepted', 'modified', 'rejected')),
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trip_user ON trips (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS feedback_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trip_id     TEXT,
    action      TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_traces (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    plan_snapshot  TEXT NOT NULL DEFAULT '[]',
    dispatches     TEXT NOT NULL DEFAULT '[]',  -- [{agent, status, ms}, ...]
    critic_verdict TEXT,
    total_tokens   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trace_session ON agent_traces (session_id, created_at);

CREATE TABLE IF NOT EXISTS kb_documents (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    city        TEXT,
    category    TEXT NOT NULL,
    source      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ready',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    city        TEXT,
    category    TEXT NOT NULL,
    embedding   TEXT,                -- JSON 浮点数组；NULL=未向量化（词面通道兜底）
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON kb_chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_chunk_city ON kb_chunks (city);
"""


def sqlite_path_from_url(database_url: str) -> Path:
    """支持 sqlite:///relative 和 sqlite:////absolute 两种形式。"""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError(f"不支持的 SQLite URL: {database_url}")
    return Path(database_url[len(prefix) :])


class SqliteProfileRepository:
    """ProfileRepository 协议的 SQLite 实现（委托 SqliteStore）。"""

    def __init__(self, store: SqliteStore) -> None:
        self._store = store

    async def get(self, user_id: str) -> UserProfile:
        return await self._store.load_profile(user_id)

    async def save(self, profile: UserProfile) -> None:
        await self._store.save_profile(profile)


class SqliteStore:
    """单连接 + WAL；写操作串行（SQLite 单写者），读走同一连接（MVP 无并发瓶颈）。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # —— 画像 ——

    async def upsert_user(self, user_id: str, nickname: str | None = None) -> None:
        await self._conn.execute(  # type: ignore[union-attr]
            "INSERT OR IGNORE INTO users (id, nickname) VALUES (?, ?)", (user_id, nickname)
        )
        await self._conn.commit()

    async def save_profile(self, profile: UserProfile) -> None:
        assert self._conn is not None
        await self.upsert_user(profile.user_id)
        await self._conn.execute(
            """INSERT INTO user_profiles (user_id, persona_types, traits, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET persona_types=excluded.persona_types,
                   traits=excluded.traits, updated_at=excluded.updated_at""",
            (
                profile.user_id,
                json.dumps(profile.persona_types),
                json.dumps(profile.traits),
                datetime.now().isoformat(),
            ),
        )
        for p in profile.preferences:
            await self._conn.execute(
                """INSERT INTO user_preferences
                       (user_id, dimension, value, sentiment, weight,
                        source, expires_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, dimension, value) DO UPDATE SET
                       sentiment=excluded.sentiment, weight=excluded.weight,
                       source=excluded.source, expires_at=excluded.expires_at,
                       updated_at=excluded.updated_at""",
                (
                    profile.user_id,
                    p.dimension,
                    p.value,
                    p.sentiment,
                    p.weight,
                    p.source,
                    p.expires_at.isoformat() if p.expires_at else None,
                    p.updated_at.isoformat(),
                ),
            )
        await self._conn.commit()

    async def load_profile(self, user_id: str) -> UserProfile:
        assert self._conn is not None
        await self.upsert_user(user_id)
        row = await (
            await self._conn.execute(
                "SELECT persona_types, traits FROM user_profiles WHERE user_id = ?", (user_id,)
            )
        ).fetchone()
        prefs_rows = await (
            await self._conn.execute(
                "SELECT dimension, value, sentiment, weight, source, expires_at, updated_at "
                "FROM user_preferences WHERE user_id = ? ORDER BY weight DESC",
                (user_id,),
            )
        ).fetchall()
        preferences = [
            Preference(
                dimension=r["dimension"],
                value=r["value"],
                sentiment=r["sentiment"],
                weight=r["weight"],
                source=r["source"],
                expires_at=datetime.fromisoformat(r["expires_at"]) if r["expires_at"] else None,
                updated_at=(
                    datetime.fromisoformat(r["updated_at"]) if r["updated_at"] else datetime.now()
                ),
            )
            for r in prefs_rows
        ]
        return UserProfile(
            user_id=user_id,
            persona_types=json.loads(row["persona_types"]) if row else [],
            traits=json.loads(row["traits"]) if row else {},
            preferences=preferences,
        )

    # —— 会话消息 ——

    async def ensure_session(self, session_id: str, user_id: str) -> None:
        await self.upsert_user(user_id)  # 防御式：保证外键成立，不依赖调用方先建用户
        await self._conn.execute(  # type: ignore[union-attr]
            "INSERT OR IGNORE INTO chat_sessions (id, user_id) VALUES (?, ?)", (session_id, user_id)
        )
        await self._conn.commit()

    async def append_message(self, session_id: str, role: str, content: str) -> None:
        await self._conn.execute(  # type: ignore[union-attr]
            "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )
        await self._conn.commit()

    # —— 攻略 ——

    async def save_trip(self, record: dict[str, Any]) -> None:
        await self.upsert_user(record["user_id"])
        await self._conn.execute(  # type: ignore[union-attr]
            """INSERT OR IGNORE INTO trips (id, user_id, session_id, final_answer, findings,
                                           profile_snapshot, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                record["trip_id"],
                record["user_id"],
                record["session_id"],
                record["final_answer"],
                json.dumps(record["findings"], ensure_ascii=False),
                json.dumps(record["profile_snapshot"], ensure_ascii=False),
                record.get("status", "draft"),
            ),
        )
        await self._conn.commit()

    async def get_trip(self, trip_id: str, user_id: str) -> dict[str, Any] | None:
        row = await (
            await self._conn.execute(  # type: ignore[union-attr]
                "SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
            )
        ).fetchone()
        if row is None:
            return None
        feedback_rows = await (
            await self._conn.execute(  # type: ignore[union-attr]
                "SELECT action, detail FROM feedback_events WHERE trip_id = ?", (trip_id,)
            )
        ).fetchall()
        return {
            "trip_id": row["id"],
            "user_id": row["user_id"],
            "session_id": row["session_id"],
            "final_answer": row["final_answer"],
            "findings": json.loads(row["findings"]),
            "profile_snapshot": json.loads(row["profile_snapshot"]),
            "status": row["status"],
            "feedback": [
                {"action": r["action"], "detail": json.loads(r["detail"])} for r in feedback_rows
            ],
        }

    async def list_trips(self, user_id: str) -> list[dict[str, Any]]:
        rows = await (
            await self._conn.execute(  # type: ignore[union-attr]
                "SELECT * FROM trips WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            )
        ).fetchall()
        return [
            {
                "trip_id": r["id"],
                "status": r["status"],
                "answer_head": r["final_answer"][:100],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    async def update_trip_status(
        self, trip_id: str, user_id: str, status: str, feedback: dict
    ) -> bool:
        cursor = await self._conn.execute(  # type: ignore[union-attr]
            "UPDATE trips SET status = ? WHERE id = ? AND user_id = ?", (status, trip_id, user_id)
        )
        await self._conn.execute(  # type: ignore[union-attr]
            "INSERT INTO feedback_events (user_id, trip_id, action, detail) VALUES (?, ?, ?, ?)",
            (user_id, trip_id, feedback["action"], json.dumps(feedback, ensure_ascii=False)),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    # —— 统计（健康检查）——

    async def counts(self) -> dict[str, int]:
        assert self._conn is not None
        sessions = await (
            await self._conn.execute("SELECT COUNT(*) c FROM chat_sessions")
        ).fetchone()
        trips = await (await self._conn.execute("SELECT COUNT(*) c FROM trips")).fetchone()
        return {"sessions": sessions["c"], "trips": trips["c"]}

    # —— 知识库 ——

    async def save_document(
        self,
        *,
        doc_id: str,
        title: str,
        city: str | None,
        category: str,
        source: str,
        chunks: list[dict[str, Any]],  # [{content, embedding(list[float] | None)}]
    ) -> int:
        await self._conn.execute(  # type: ignore[union-attr]
            """INSERT OR REPLACE INTO kb_documents (id, title, city, category, source, status)
               VALUES (?, ?, ?, ?, ?, 'ready')""",
            (doc_id, title, city, category, source),
        )
        await self._conn.execute("DELETE FROM kb_chunks WHERE document_id = ?", (doc_id,))  # type: ignore[union-attr]
        for i, c in enumerate(chunks):
            await self._conn.execute(
                "INSERT INTO kb_chunks"
                " (document_id, content, chunk_index, city, category, embedding)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    doc_id,
                    c["content"],
                    i,
                    city,
                    category,
                    json.dumps(c["embedding"]) if c.get("embedding") else None,
                ),
            )
        await self._conn.commit()
        return len(chunks)

    async def load_chunks(self, city: str | None = None) -> list[dict[str, Any]]:
        """加载切片（可按城市过滤）。embedding 以 JSON 解包；None 表示未向量化。"""
        sql = (
            "SELECT c.id, c.content, c.city, c.category, c.embedding, d.title, d.source "
            "FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id"
        )
        params: tuple = ()
        if city:
            sql += " WHERE c.city = ? OR c.city IS NULL"
            params = (city,)
        rows = await (await self._conn.execute(sql, params)).fetchall()  # type: ignore[union-attr]
        return [
            {
                "chunk_id": r["id"],
                "content": r["content"],
                "city": r["city"],
                "category": r["category"],
                "title": r["title"],
                "source": r["source"],
                "embedding": json.loads(r["embedding"]) if r["embedding"] else None,
            }
            for r in rows
        ]

    # —— 编排 trace ——

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
        await self.upsert_user(user_id)
        await self._conn.execute(  # type: ignore[union-attr]
            """INSERT INTO agent_traces (session_id, user_id, plan_snapshot, dispatches,
                                         critic_verdict, total_tokens)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                user_id,
                json.dumps(plan_snapshot, ensure_ascii=False),
                json.dumps(dispatches, ensure_ascii=False),
                json.dumps(critic_verdict, ensure_ascii=False) if critic_verdict else None,
                total_tokens,
            ),
        )
        await self._conn.commit()
