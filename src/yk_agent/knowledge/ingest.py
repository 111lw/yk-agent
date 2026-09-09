"""知识库灌入：文档 → 切片 → embedding（可失败降级）→ SQLite。"""

from __future__ import annotations

import hashlib
import logging

from yk_agent.knowledge.models import KbDocument, chunk_document
from yk_agent.llm.provider import LLMProvider
from yk_agent.storage.sqlite import SqliteStore

logger = logging.getLogger(__name__)


async def ingest_documents(
    store: SqliteStore,
    provider: LLMProvider,
    docs: list[KbDocument],
    *,
    embed: bool = True,
) -> tuple[int, int]:
    """批量灌库。返回 (文档数, 切片数)。

    - embed=False 或 embedding 失败：切片以 NULL 向量入库（词面通道兜底），不阻塞灌库；
    - doc_id 由 title+source 哈希生成——同文档重复灌库 = 覆盖更新（幂等），
      embedding 模型就绪后带向量重灌一遍即可。
    """
    doc_count, chunk_count = 0, 0
    for doc in docs:
        texts = chunk_document(doc)
        embeddings: list[list[float] | None]
        if embed:
            try:
                vectors = await provider.embed(texts)
                embeddings = list(vectors)
            except Exception as e:  # noqa: BLE001 — 降级入库
                logger.warning("文档《%s》向量化失败（以无向量入库）: %s", doc.title, e)
                embeddings = [None] * len(texts)
        else:
            embeddings = [None] * len(texts)

        doc_id = hashlib.sha1(f"{doc.title}|{doc.source}".encode()).hexdigest()[:16]
        n = await store.save_document(
            doc_id=doc_id,
            title=doc.title,
            city=doc.city,
            category=doc.category,
            source=doc.source,
            chunks=[{"content": t, "embedding": e} for t, e in zip(texts, embeddings, strict=True)],
        )
        doc_count += 1
        chunk_count += n
        logger.info("灌库《%s》: %d 切片", doc.title, n)
    return doc_count, chunk_count
