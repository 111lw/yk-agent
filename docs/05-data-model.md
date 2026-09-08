# 05 数据模型

> 存储选型：**全环境 SQLite**（决策见 `docs/decisions/ADR-002-sqlite.md`）。
> schema 唯一事实来源是 `src/yk_agent/storage/sqlite.py` 的 `_SCHEMA`（本篇讲设计意图，DDL 有变更必须同步该文件并更新本篇）。
> 初始化：`python scripts/init_db.py`（幂等建库建表）。

## 库表总览

```
users               用户
user_profiles       L1 静态人格（1:1 users）
user_preferences    L2 动态偏好（1:N）
feedback_events     L3 行为反馈
chat_sessions       会话
chat_messages       消息
trips               生成的攻略
agent_traces        编排 trace（可观测性）
```

> 知识库表（kb_documents / kb_chunks）随 RAG 阶段实现时加入，向量以 JSON 存取 + 内存余弦计算（ADR-002）。

## 关键设计

### users / user_profiles
- `users.id`: TEXT 主键——MVP 匿名体系直接使用外部 `X-User-Id` 标识，不接注册。
- `user_profiles.persona_types`: JSON 数组，最多 2 个旅行人格枚举值（见 04 文档）。
- `user_profiles.traits`: JSON，Big Five 简化分值（0~1），允许缺省。

### user_preferences（L2 偏好，更新最频繁的表）
- 唯一约束 `(user_id, dimension, value)` —— 抽取器合并按此 upsert。
- `weight REAL`、`sentiment`、`source`、`expires_at`（时点性偏好）。
- `value_embedding`：V2 引入（向量以 JSON 存取 + 内存余弦召回，见 ADR-002）。

### trips（攻略）
- `findings`：JSON，各子智能体产出快照（poi/route/budget 的完整结构化输出）。
- `profile_snapshot`：**生成时所用画像快照**——画像会变，攻略的可解释性绑定生成时点。
- `status`: draft / accepted / modified / rejected。

### agent_traces（编排 trace，调试自主编排的唯一依据）
- `plan_snapshot`、`dispatches`（每次派发：agent/status/ms）、`critic_verdict`、`total_tokens`。
- 只增不改；由 chat 路由在编排结束后写入（`api/routes/chat.py`）。

### feedback_events（L3 反馈）
- trips 反馈时同步落一条；画像 weight 回写逻辑属 V2（docs/04 §反馈回写）。

## 会话缓存

- 热数据在进程内存（`AppState.sessions`）；消息与攻略持久化在 SQLite，重启不丢。
- MVP 单实例部署，无分布式缓存需求（ADR-002）。

## 迁移策略

- schema 变更 = 修改 `storage/sqlite.py` 的 `_SCHEMA`（CREATE TABLE IF NOT EXISTS，幂等）。
- 破坏性变更（改列类型/删列）出现时：引入备份-重建脚本或迁移表版本号（`PRAGMA user_version`），届时登记 roadmap。
- 未来若需水平扩展再迁 PG：repository 协议已隔离，迁移面 = storage 层一个包（ADR-002）。
