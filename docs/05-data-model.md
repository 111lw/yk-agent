# 05 数据模型

> 建表 DDL 的唯一事实来源是 `scripts/init_db.sql`（本篇讲设计意图，DDL 有变更必须同步该文件并更新本篇）。

## 库表总览

```
users               用户
user_profiles       L1 静态人格（1:1 users）
user_preferences    L2 动态偏好（1:N）
feedback_events     L3 行为反馈（1:N）
chat_sessions       会话
chat_messages       消息
trips               生成的攻略
agent_traces        编排 trace（可观测性）
kb_documents        知识库文档
kb_chunks           知识库切片（pgvector）
```

## 关键设计

### users / user_profiles
- `users`: 业务侧唯一标识（MVP 用匿名 id + 昵称即可，不接手机号注册）。
- `user_profiles.persona_types`: `text[]`，最多 2 个旅行人格枚举值（见 04 文档）。
- `user_profiles.traits`: jsonb，Big Five 简化分值（0~1），允许缺省。

### user_preferences（L2 偏好，更新最频繁的表）
- 唯一约束 `(user_id, dimension, value)` —— 抽取器合并按此 upsert。
- `weight numeric(3,2)`、`sentiment`、`source`、`expires_at timestamptz`（时点性偏好）。
- `value_embedding vector(1024)`：value 规范化后同文本的 embedding，用于"用户提过类似偏好"的语义召回。维度以 `MODEL_EMBEDDING` 实际输出为准，**改动需同步 init_db.sql 与 config**。

### trips（攻略）
- `plan jsonb`：完整行程结构（逐日 → 时段 → POI 引用 + 说明）。
- `budget jsonb`：分项预算。
- `profile_snapshot jsonb`：**生成时所用画像快照**——画像会变，攻略的可解释性绑定生成时点。
- `status`: draft / accepted / modified / rejected。

### agent_traces（编排 trace，调试自主编排的唯一依据）
- `plan_snapshot jsonb`、`dispatches jsonb[]`（每次派发：agent/输入摘要/token/耗时）、`critic_verdict jsonb`、`total_tokens int`。
- 只增不改；MVP 不做聚合分析，能按 session_id 查即可。

### kb_documents / kb_chunks（RAG）
- `kb_documents`: 目的地/主题/来源/清洗状态。
- `kb_chunks`: 切片文本 + `embedding vector(1024)` + 元数据（city、category、tags text[]）。检索过滤主要走 `city + category`，向量召回 + 标签加权（见 04 文档双通道）。
- 建索引：`CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)`。

## Redis 键约定

| key | 内容 | TTL |
|---|---|---|
| `session:{session_id}:messages` | 会话消息环形缓冲（list，≤50 条） | 7d |
| `session:{session_id}:state` | 进行中编排的状态快照（checkpoint 兜底在 PG） | 1h |
| `ratelimit:{user_id}` | 简单限流计数 | 1min |

## 迁移策略

- MVP：`scripts/init_db.py` 幂等执行 `scripts/init_db.sql`（IF NOT EXISTS）。
- 引入 Alembic 的时机：出现第一个"改已有表"的需求时（记入 roadmap V2）。
