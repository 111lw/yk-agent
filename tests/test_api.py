"""API 层测试：注入 MockMap + MockLLM，全离线验证 SSE 事件序列与画像/攻略接口。"""

import json

import pytest
from fastapi.testclient import TestClient

from yk_agent.api.deps import get_state
from yk_agent.api.main import app
from yk_agent.api.state import AppState
from yk_agent.llm.mock import MockLLMProvider
from yk_agent.mcp.map.provider import MockMapProvider


def _plan() -> str:
    return json.dumps(
        {
            "plan": [
                {
                    "agent": "poi-agent",
                    "instruction": "城市=大理 关键词=景点,美食",
                    "depends_on": [],
                },
                {"agent": "route-agent", "instruction": "天数=2", "depends_on": ["poi-agent"]},
                {"agent": "budget-agent", "instruction": "天数=2", "depends_on": ["route-agent"]},
            ]
        },
        ensure_ascii=False,
    )


@pytest.fixture()
def client():
    llm = MockLLMProvider(
        [_plan(), json.dumps({"passed": True, "reasons": []}), "这是你的大理攻略"]
    )
    state = AppState(provider=llm, map_provider=MockMapProvider())
    app.dependency_overrides[get_state] = lambda: state
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_chat_sse_event_sequence(client):
    with client.stream(
        "POST", "/api/chat", json={"message": "想去大理玩2天"}, headers={"X-User-Id": "u1"}
    ) as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and name:
                events.append((name, json.loads(line.split(":", 1)[1])))

    names = [n for n, _ in events]
    # 事件序列契约：session 最先，plan_update 在 agent 事件前，token 在 done 前
    assert names[0] == "session"
    assert names.index("plan_update") < names.index("agent_start")
    assert "token" in names and names[-1] == "done"

    data = dict(events)
    assert data["token"]["text"] == "这是你的大理攻略"
    assert data["done"]["trip_id"]  # 有攻略产出 → 存档并返回 trip_id


def test_chat_saves_trip_and_profile_writeback(client):
    # 第一轮对话产生 trip 与画像
    with client.stream(
        "POST",
        "/api/chat",
        json={"message": "想去大理玩2天，不想爬山"},
        headers={"X-User-Id": "u2"},
    ) as resp:
        resp.read()  # SSE 全量消费，触发回写

    profile = client.get("/api/profile", headers={"X-User-Id": "u2"}).json()
    # MockLLM 只会输出规划 JSON，抽取器第二次调用返回的是 pass JSON → 解析为空增量（降级合法）
    assert "profile" in profile and "summary" in profile

    trips = client.get("/api/trips", headers={"X-User-Id": "u2"}).json()
    assert len(trips) == 1
    trip_id = trips[0]["trip_id"]

    detail = client.get(f"/api/trips/{trip_id}", headers={"X-User-Id": "u2"}).json()
    assert detail["status"] == "draft"
    assert set(detail["findings"]) == {"poi-agent", "route-agent", "budget-agent"}

    fb = client.post(
        f"/api/trips/{trip_id}/feedback",
        json={"action": "accept", "detail": "不错"},
        headers={"X-User-Id": "u2"},
    ).json()
    assert fb["status"] == "accepted"

    # 他人不可见
    assert client.get(f"/api/trips/{trip_id}", headers={"X-User-Id": "u3"}).status_code == 404


def test_profile_put_merges_preferences(client):
    headers = {"X-User-Id": "u4"}
    resp = client.put(
        "/api/profile",
        json={
            "persona_types": ["美食型"],
            "preferences": [
                {
                    "dimension": "food",
                    "value": "spicy",
                    "sentiment": "like",
                    "weight": 0.6,
                    "source": "manual",
                }
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200
    profile = resp.json()["profile"]
    assert profile["persona_types"] == ["美食型"]
    assert profile["preferences"][0]["value"] == "spicy"

    # 二次修正为 dislike → 矛盾合并规则生效（减半再累加）
    resp = client.put(
        "/api/profile",
        json={
            "preferences": [
                {
                    "dimension": "food",
                    "value": "spicy",
                    "sentiment": "dislike",
                    "weight": -0.6,
                    "source": "manual",
                }
            ]
        },
        headers=headers,
    )
    pref = resp.json()["profile"]["preferences"][0]
    assert pref["sentiment"] == "dislike"
    assert pref["weight"] == pytest.approx(0.6 * 0.5 - 0.6)


def test_chat_session_reuse(client):
    with client.stream(
        "POST", "/api/chat", json={"message": "你好"}, headers={"X-User-Id": "u5"}
    ) as resp:
        resp.read()
    # session 历史落档
    state = app.dependency_overrides[get_state]()
    assert len(state.sessions) == 1
    sess = next(iter(state.sessions.values()))
    assert sess.history[0]["role"] == "user"
