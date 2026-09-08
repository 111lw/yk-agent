# ADR-002：存储选型全环境 SQLite

- 状态：已采纳
- 日期：2026-09-08
- 关联文档：`docs/05-data-model.md`、`docs/02-architecture.md`

## 背景

初版设计为 PostgreSQL + pgvector（主存储）+ Redis（缓存）。实际开发环境为 Windows 单机、无 Docker，
安装 PG 成本高；且 MVP 数据规模（个位数用户、百级攻略）远未触及 SQLite 上限。经决策：**所有环境
统一使用 SQLite**，不再区分开发/生产存储。

## 决策

| 项 | 原设计 | 现决策 |
|---|---|---|
| 主存储 | PostgreSQL + pgvector | **SQLite**（`aiosqlite` 异步驱动，WAL 模式） |
| 会话缓存 | Redis | 内存缓存（进程内 dict）+ SQLite 落库 |
| 向量检索 | pgvector + HNSW | 向量列以 JSON 存取 + 内存余弦计算（知识库实现时引入 numpy/sqlite-vec，规模小够用） |

- schema 唯一事实来源：`src/yk_agent/storage/sqlite.py`（原 `scripts/init_db.sql` 已删除）。
- 存储访问全部经 repository/store 接口，业务层不感知 SQL 方言。

## 后果

- 正面：零运维、Windows/CI 环境一致、文件即备份（拷库即迁移）、开发调试直观。
- 负面/风险与对策：
  - 单写者并发上限 → MVP 单实例部署足够；写操作经单连接串行，不会触发锁冲突。
  - 无服务端向量索引 → 知识库规模控制在万级切片内，内存检索可扛；超出再评估 sqlite-vec 或回迁 PG。
  - 多实例部署不可用（SQLite 文件锁）→ 部署形态定为单实例；未来确需水平扩展时再启 PG 迁移
    （repository 协议已隔离，迁移面 = storage 层一个包）。
- 依赖变化：移除 `psycopg` / `pgvector` / `redis`，新增 `aiosqlite`。
