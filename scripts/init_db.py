"""初始化数据库（SQLite）：建库文件并执行内建 schema（幂等）。

schema 唯一事实来源：src/yk_agent/storage/sqlite.py（PG 版 DDL 已随全环境 SQLite
决策移除，见 docs/decisions/ADR-002-sqlite.md）。

用法：conda activate yk-agent && python scripts/init_db.py
"""

import asyncio
import sys

from yk_agent.config import settings
from yk_agent.storage.sqlite import SqliteStore, sqlite_path_from_url


async def main() -> int:
    path = sqlite_path_from_url(settings.database_url)
    store = SqliteStore(path)
    await store.connect()
    # 输出避免 emoji：Windows 终端默认 GBK 无法编码，会导致 UnicodeEncodeError
    print(f"[ok] SQLite ready: {path.resolve()}")
    await store.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
