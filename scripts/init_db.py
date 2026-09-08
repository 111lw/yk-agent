"""初始化数据库（SQLite）：建库文件并执行内建 schema（幂等）。

schema 唯一事实来源：src/yk_agent/storage/sqlite.py（PG 版 DDL 已随全环境 SQLite
决策移除，见 docs/decisions/ADR-002-sqlite.md）。

用法：conda activate yk-agent && python scripts/init_db.py
"""

import asyncio
import sys

from yk_agent.config import settings
from yk_agent.storage.sqlite import SqliteStore, sqlite_path_from_url


def _force_utf8_stdout() -> None:
    """Windows 终端默认用 GBK(cp936) 编码 stdout，打印 ✅/中文会抛 UnicodeEncodeError。

    与其迁就终端删掉可读字符，不如显式把输出切回 UTF-8（Windows Terminal + TrueType
    字体可正常显示）。若终端实在不认 UTF-8，reconfigure 会失败——静默跳过，不崩脚本。
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):  # 非流对象 / 无 reconfigure（极老 Python）
        pass


_force_utf8_stdout()


async def main() -> int:
    path = sqlite_path_from_url(settings.database_url)
    store = SqliteStore(path)
    await store.connect()
    print(f"✅ SQLite 就绪: {path.resolve()}")
    await store.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
