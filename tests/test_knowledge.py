"""知识库单测：切片 / 灌库 / 混合检索（语义 + 词面降级）/ poi-agent 接入。

MockLLMProvider 的 embed 返回与文本绑定维度的常向量——用"语义相似 = 向量同向"
的最小假设来测通道选择与打分逻辑，不发真实请求。
"""

import pytest

from yk_agent.knowledge.ingest import ingest_documents
from yk_agent.knowledge.models import KbDocument, chunk_document
from yk_agent.knowledge.retriever import KbRetriever, _cosine, _lexical_score
from yk_agent.llm.mock import MockLLMProvider
from yk_agent.mcp.map.provider import MockMapProvider
from yk_agent.storage.sqlite import SqliteStore


class _FakeEmbedProvider(MockLLMProvider):
    """按文本首字符给出稳定向量的假 embedding（"乳"与"烤乳扇"语义相近的模拟）。"""

    _AXES = {"乳": [1.0, 0.0, 0.0], "海": [0.0, 1.0, 0.0], "路": [0.0, 0.0, 1.0]}

    async def embed(self, texts):
        out = []
        for t in texts:
            axis = self._AXES.get(t[0], [0.33, 0.33, 0.33])
            out.append(axis)
        return out


@pytest.fixture()
async def store(tmp_path):
    s = SqliteStore(tmp_path / "kb.db")
    await s.connect()
    yield s
    await s.close()


DOCS = [
    KbDocument(
        title="乳扇指南",
        city="大理",
        category="food",
        source="t",
        content="烤乳扇夹玫瑰酱是经典吃法。乳扇是白族奶制品。",
    ),
    KbDocument(
        title="洱海指南",
        city="大理",
        category="guide",
        source="t",
        content="环洱海骑行看日落。洱海是大理的湖。",
    ),
]


# ---------- 切片 ----------


def test_chunk_document_merges_paragraphs():
    doc = KbDocument(
        title="t",
        category="guide",
        source="s",
        content="段落一" + "很" * 200 + "\n\n" + "段落二" + "很" * 200,
    )
    chunks = chunk_document(doc)
    assert len(chunks) == 2 and all(len(c) <= 301 for c in chunks)


def test_chunk_document_empty_falls_back_to_whole():
    doc = KbDocument(title="t", category="g", source="s", content="只有一段")
    assert chunk_document(doc) == ["只有一段"]


# ---------- 打分函数 ----------


def test_cosine_identical_and_orthogonal():
    assert _cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert _cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert _cosine([1, 0], [1]) == 0.0  # 维度不一致安全


def test_lexical_score_proper_noun_strong():
    score_hit = _lexical_score("崇圣寺三塔", "崇圣寺三塔在大理古城北侧")
    score_miss = _lexical_score("崇圣寺三塔", "洱海环湖骑行")
    assert score_hit > 0.4 > score_miss == 0.0


# ---------- 灌库与检索 ----------


async def test_ingest_and_semantic_search(store):
    provider = _FakeEmbedProvider()
    n_docs, n_chunks = await ingest_documents(store, provider, DOCS)
    assert n_docs == 2 and n_chunks >= 2

    retriever = KbRetriever(store, provider)
    hits = await retriever.search("乳扇怎么吃", city="大理", top_k=2)
    assert hits and hits[0]["channel"] == "hybrid"
    assert "乳扇" in hits[0]["content"]  # 语义通道命中的是正确文档
    assert hits[0]["score"] >= hits[-1]["score"]


async def test_ingest_idempotent_overwrites(store):
    provider = _FakeEmbedProvider()
    await ingest_documents(store, provider, DOCS)
    await ingest_documents(store, provider, DOCS)  # 重复灌库 = 覆盖
    chunks = await store.load_chunks()
    titles = {c["title"] for c in chunks}
    assert titles == {"乳扇指南", "洱海指南"}  # 无重复文档


async def test_search_degrades_to_lexical_when_embed_fails(store):
    class _BrokenEmbed(MockLLMProvider):
        async def embed(self, texts):
            raise RuntimeError("embedding 不可用")

    provider = _BrokenEmbed()
    await ingest_documents(store, provider, DOCS)  # 无向量入库
    retriever = KbRetriever(store, provider)
    hits = await retriever.search("乳扇", top_k=2)
    assert hits and all(h["channel"] == "lexical" for h in hits)
    assert "乳扇" in hits[0]["content"]


async def test_search_empty_kb_returns_empty(store):
    retriever = KbRetriever(store, MockLLMProvider())
    assert await retriever.search("任意", top_k=3) == []


# ---------- poi-agent 接入 ----------


def _poi_payload() -> dict:
    return {"agent": "poi-agent", "instruction": "城市=大理 关键词=景点", "user_profile": {}}


async def test_poi_agent_includes_kb_tips(store):
    from yk_agent.agents.poi_agent import make_poi_agent

    provider = _FakeEmbedProvider()
    await ingest_documents(store, provider, DOCS)
    kb = KbRetriever(store, provider)
    run = make_poi_agent(MockMapProvider(), kb=kb)
    out = await run(_poi_payload())
    assert out["kb_tips"], "poi-agent 应带回知识库要点"
    assert any("乳扇" in t or "洱海" in t for t in out["kb_tips"])


async def test_poi_agent_kb_failure_does_not_break(store):
    from yk_agent.agents.poi_agent import make_poi_agent

    class _BrokenKb:
        async def search(self, *a, **k):
            raise RuntimeError("kb 挂了")

    run = make_poi_agent(MockMapProvider(), kb=_BrokenKb())  # type: ignore[arg-type]
    out = await run(_poi_payload())
    assert out["kb_tips"] == [] and len(out["pois"]) > 0  # 主产出不受影响
