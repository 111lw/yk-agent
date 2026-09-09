"""知识库灌库脚本：JSON 文档列表 → 切片 → embedding（可降级）→ SQLite。

用法：
    conda activate yk-agent
    python scripts/ingest_kb.py scripts/kb_samples.json            # 带向量灌库
    python scripts/ingest_kb.py scripts/kb_samples.json --no-embed # 纯词面灌库

JSON 格式：[{"title", "city", "category", "source", "content"}, ...]
幂等：同一 title+source 重复灌库为覆盖更新；embedding 模型就绪后重灌即升级为向量库。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from yk_agent.knowledge.ingest import ingest_documents
from yk_agent.knowledge.models import KbDocument


def _force_utf8_stdout() -> None:
    """Windows 终端默认 GBK 编码 stdout，打印 ✅/中文会抛 UnicodeEncodeError（同 init_db.py）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


_force_utf8_stdout()


async def main(path: str, embed: bool) -> int:
    from yk_agent.config import settings
    from yk_agent.llm.factory import get_provider
    from yk_agent.storage.sqlite import SqliteStore, sqlite_path_from_url

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    docs = [KbDocument.model_validate(d) for d in raw]

    store = SqliteStore(sqlite_path_from_url(settings.database_url))
    await store.connect()
    provider = get_provider()
    n_docs, n_chunks = await ingest_documents(store, provider, docs, embed=embed)
    mode = "语义+词面混合" if embed else "纯词面（embedding 未启用）"
    print(f"✅ 灌库完成: {n_docs} 篇文档 / {n_chunks} 个切片，检索模式: {mode}")
    await store.close()
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--no-embed"]
    target = args[0] if args else str(Path(__file__).parent / "kb_samples.json")
    sys.exit(asyncio.run(main(target, embed="--no-embed" not in sys.argv)))
