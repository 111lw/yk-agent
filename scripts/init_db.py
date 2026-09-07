"""初始化数据库：幂等执行 init_db.sql（DDL 事实来源，设计说明见 docs/05-data-model.md）。

用法：conda activate yk-agent && python scripts/init_db.py
依赖：DATABASE_URL 环境变量（见 .env.example）。
"""

import asyncio
import sys
from pathlib import Path

SQL_PATH = Path(__file__).parent / "init_db.sql"


async def main() -> int:
    import psycopg

    from yk_agent.config import settings

    print(f"连接数据库并执行 {SQL_PATH.name} ...")
    # MVP 用同步连接分语句执行即可；语句以分号切分依赖 SQL 文件内不含过程块
    conninfo = settings.database_url
    with psycopg.connect(conninfo) as conn:
        conn.execute(SQL_PATH.read_text(encoding="utf-8"))
        conn.commit()
    print("✅ 数据库初始化完成")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
