"""SQLite 存储层测试：画像/会话/攻略/trace 全链路持久化（tmp_path 隔离）。"""

import pytest

from yk_agent.profile.models import Preference, UserProfile
from yk_agent.storage.sqlite import SqliteProfileRepository, SqliteStore, sqlite_path_from_url


@pytest.fixture()
async def store(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    await store.connect()
    yield store
    await store.close()


async def test_sqlite_path_url_parsing():
    assert sqlite_path_from_url("sqlite:///data/yk.db").name == "yk.db"
    with pytest.raises(ValueError, match="不支持"):
        sqlite_path_from_url("postgresql://localhost/yk")


async def test_profile_roundtrip(store):
    repo = SqliteProfileRepository(store)
    profile = UserProfile(
        user_id="u1",
        persona_types=["美食型"],
        preferences=[
            Preference(
                dimension="food", value="spicy", sentiment="like", weight=0.7, source="chat:1"
            )
        ],
    )
    await repo.save(profile)

    loaded = await repo.get("u1")
    assert loaded.persona_types == ["美食型"]
    assert loaded.preferences[0].value == "spicy"
    assert loaded.preferences[0].weight == 0.7


async def test_profile_upsert_no_duplicate(store):
    repo = SqliteProfileRepository(store)
    for weight, source in ((0.5, "s1"), (0.8, "s2")):
        await repo.save(
            UserProfile(
                user_id="u1",
                preferences=[
                    Preference(
                        dimension="pace",
                        value="slow",
                        sentiment="like",
                        weight=weight,
                        source=source,
                    )
                ],
            )
        )
    loaded = await repo.get("u1")
    assert len(loaded.preferences) == 1  # UNIQUE(user_id,dimension,value) upsert，不重复
    assert loaded.preferences[0].weight == 0.8 and loaded.preferences[0].source == "s2"


async def test_session_and_messages(store):
    await store.ensure_session("s1", "u1")
    await store.ensure_session("s1", "u1")  # 幂等
    await store.append_message("s1", "user", "想去大理")
    await store.append_message("s1", "assistant", "好的")
    counts = await store.counts()
    assert counts["sessions"] == 1


async def test_trip_save_get_feedback(store):
    await store.ensure_session("s1", "u1")
    await store.save_trip(
        {
            "trip_id": "t1",
            "user_id": "u1",
            "session_id": "s1",
            "final_answer": "攻略正文",
            "findings": {"poi-agent": {"ok": True, "data": {"city": "大理"}}},
            "profile_snapshot": {"persona_types": []},
            "status": "draft",
        }
    )
    trip = await store.get_trip("t1", "u1")
    assert trip is not None and trip["status"] == "draft"
    assert trip["findings"]["poi-agent"]["data"]["city"] == "大理"

    # 他人不可见
    assert await store.get_trip("t1", "u2") is None

    ok = await store.update_trip_status("t1", "u1", "accepted", {"action": "accept", "detail": ""})
    assert ok is True
    trip = await store.get_trip("t1", "u1")
    assert trip["status"] == "accepted" and trip["feedback"][0]["action"] == "accept"

    assert await store.update_trip_status("t404", "u1", "accepted", {"action": "accept"}) is False


async def test_trace_written(store):
    await store.ensure_session("s1", "u1")
    await store.write_trace(
        session_id="s1",
        user_id="u1",
        plan_snapshot=[{"agent": "poi-agent", "instruction": "x", "depends_on": []}],
        dispatches=[{"agent": "poi-agent", "status": "ok", "ms": 123}],
        critic_verdict={"passed": True, "reasons": []},
        total_tokens=456,
    )
    row = await (await store._conn.execute("SELECT * FROM agent_traces")).fetchone()
    assert row["total_tokens"] == 456
    assert "poi-agent" in row["dispatches"]
