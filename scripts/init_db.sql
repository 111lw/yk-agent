-- ============================================================
-- yk-agent 数据库初始化（DDL 唯一事实来源，设计说明见 docs/05-data-model.md）
-- 执行：python scripts/init_db.py（幂等）
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- 用户（MVP：匿名体系，不接手机号注册）
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nickname    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- L1 静态人格（1:1 users，见 docs/04-user-profile.md）
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id      UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    persona_types TEXT[] NOT NULL DEFAULT '{}',  -- 旅行人格枚举，最多 2 个
    traits       JSONB NOT NULL DEFAULT '{}',    -- Big Five 简化分值(0~1)，允许缺省
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- L2 动态偏好（更新最频繁；抽取器按 (user_id, dimension, value) upsert）
CREATE TABLE IF NOT EXISTS user_preferences (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dimension       TEXT NOT NULL,   -- pace/budget/stay/food/transport/interest/companion
    value           TEXT NOT NULL,
    sentiment       TEXT NOT NULL DEFAULT 'neutral',  -- like/dislike/neutral
    weight          NUMERIC(3,2) NOT NULL DEFAULT 0 CHECK (weight BETWEEN -1.0 AND 1.0),
    source          TEXT NOT NULL,   -- 证据来源，可追溯（如 chat:msg-123）
    expires_at      TIMESTAMPTZ,     -- 时点性偏好（如"十一期间"）
    value_embedding vector(1024),    -- 维度须与 MODEL_EMBEDDING 输出一致，变更需同步本文档
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, dimension, value)
);
CREATE INDEX IF NOT EXISTS idx_pref_user ON user_preferences (user_id);

-- L3 行为反馈
CREATE TABLE IF NOT EXISTS feedback_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trip_id     UUID,
    action      TEXT NOT NULL,       -- accept/modify/reject/rate
    detail      JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 会话与消息
CREATE TABLE IF NOT EXISTS chat_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON chat_messages (session_id, created_at);

-- 生成的攻略（profile_snapshot 绑定生成时点的画像，保证可解释性）
CREATE TABLE IF NOT EXISTS trips (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id       UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
    destination      TEXT NOT NULL,
    plan             JSONB NOT NULL,          -- 逐日 → 时段 → POI 引用 + 说明
    budget           JSONB NOT NULL DEFAULT '{}',
    profile_snapshot JSONB NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'accepted', 'modified', 'rejected')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trip_user ON trips (user_id, created_at DESC);

-- 编排 trace（调试自主编排的唯一依据，只增不改）
CREATE TABLE IF NOT EXISTS agent_traces (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id     UUID NOT NULL,
    user_id        UUID NOT NULL,
    plan_snapshot  JSONB NOT NULL DEFAULT '{}',
    dispatches     JSONB NOT NULL DEFAULT '[]',  -- [{agent, input_digest, tokens, ms}, ...]
    critic_verdict JSONB,
    total_tokens   INT NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trace_session ON agent_traces (session_id, created_at);

-- 知识库：文档与切片
CREATE TABLE IF NOT EXISTS kb_documents (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL,
    city         TEXT,
    category     TEXT NOT NULL,      -- guide/poi/food/transport/...
    source       TEXT NOT NULL,
    raw_content  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'chunked', 'embedded', 'failed')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    chunk_index INT NOT NULL,
    city        TEXT,
    category    TEXT NOT NULL,
    tags        TEXT[] NOT NULL DEFAULT '{}',   -- 标签加权双通道（docs/04-user-profile.md）
    embedding   vector(1024),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON kb_chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_chunk_hnsw ON kb_chunks
    USING hnsw (embedding vector_cosine_ops);
