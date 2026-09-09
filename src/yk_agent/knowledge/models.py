"""知识库数据模型与切片逻辑。"""

from __future__ import annotations

from pydantic import BaseModel

MAX_CHUNK_CHARS = 300  # 切片上限（中文）；超长按段落合并切分


class KbDocument(BaseModel):
    """一篇待灌库的文档。content 按段落切为若干 chunk。"""

    title: str
    city: str | None = None
    category: str  # guide / food / transport / poi / tips ...
    source: str
    content: str


class KbHit(BaseModel):
    """一条检索命中。score ∈ [0,1]；channel 标明得分来源（可解释）。"""

    content: str
    title: str
    city: str | None
    category: str
    source: str
    score: float
    channel: str  # hybrid / lexical（semantic 不可用时）


def chunk_document(doc: KbDocument) -> list[str]:
    """按段落切分并合并到 MAX_CHUNK_CHARS 上限；空段落丢弃。"""
    chunks: list[str] = []
    buf = ""
    for para in (p.strip() for p in doc.content.split("\n")):
        if not para:
            continue
        if buf and len(buf) + len(para) + 1 > MAX_CHUNK_CHARS:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks or [doc.content]
