"""混合检索器：语义（embedding 余弦）为主 + 词面（字符二元组）兜底。

- 向量不落独立向量库：存 SQLite（JSON），查询时全量载入内存算余弦——
  万级切片以内毫秒级，规模信号出现前不引入额外基础设施（ADR-002）。
- embedding 调用失败（未配模型/限流/超时）→ 自动降级纯词面，检索不中断。
"""

from __future__ import annotations

import logging
import math
from collections import Counter

from yk_agent.llm.provider import LLMProvider
from yk_agent.storage.sqlite import SqliteStore

logger = logging.getLogger(__name__)

_W_SEMANTIC = 0.75  # 混合权重：语义通道
_W_LEXICAL = 0.25  # 混合权重：词面通道（专有名词精确匹配的补偿）


def _bigrams(text: str) -> Counter[str]:
    """字符二元组计数——中文无分词依赖的最小词面单元。"""
    cleaned = "".join(text.split())
    return Counter(cleaned[i : i + 2] for i in range(len(cleaned) - 1))


def _lexical_score(query: str, content: str) -> float:
    """二元组重叠率（类 rouge）：专有名词命中时显著高。"""
    if not query or not content:
        return 0.0
    q, c = _bigrams(query), _bigrams(content)
    if not q:
        return 0.0
    overlap = sum(min(n, c[g]) for g, n in q.items())
    return overlap / sum(q.values())


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class KbRetriever:
    """kb_search 的实现。store 必需；provider 用于 query 向量化（可失败）。"""

    def __init__(self, store: SqliteStore, provider: LLMProvider) -> None:
        self._store = store
        self._provider = provider

    async def search(
        self,
        query: str,
        *,
        city: str | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """检索知识库。返回 [{content, title, city, category, source, score, channel}]。"""
        chunks = await self._store.load_chunks(city)
        if not chunks:
            return []

        # 语义通道：query 向量化失败即降级
        q_vec: list[float] | None = None
        if any(c["embedding"] for c in chunks):
            try:
                q_vec = (await self._provider.embed([query]))[0]
            except Exception as e:  # noqa: BLE001 — 降级检索，不中断
                logger.warning("query 向量化失败，降级词面通道: %s", e)

        hits: list[dict] = []
        for c in chunks:
            lex = _lexical_score(query, c["content"])
            if q_vec is not None and c["embedding"]:
                sem = max(0.0, _cosine(q_vec, c["embedding"]))  # 余弦[-1,1] → 取非负
                score = _W_SEMANTIC * sem + _W_LEXICAL * lex
                channel = "hybrid"
            else:
                score = lex
                channel = "lexical"
            if score > 0.01:  # 完全不沾边的切片不返回
                hits.append(
                    {
                        "content": c["content"],
                        "title": c["title"],
                        "city": c["city"],
                        "category": c["category"],
                        "source": c["source"],
                        "score": round(score, 4),
                        "channel": channel,
                    }
                )

        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:top_k]
