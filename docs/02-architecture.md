# 02 总体架构

## 五层架构

```
┌─────────────────────────────────────────────────┐
│  接入层    FastAPI (SSE 流式) / 后续: Web 小程序   │
├─────────────────────────────────────────────────┤
│  编排层    Agent Core (src/yk_agent/core/)       │
│            Orchestrator ─ Planner ─ 派发 ─ Critic │
├─────────────────────────────────────────────────┤
│  能力层    SubAgents (agents/)                    │
│            Skills (skills/)   MCP 工具 (mcp/)     │
├─────────────────────────────────────────────────┤
│  知识层    用户画像 (profile/)  RAG 知识库(knowledge/)│
│            记忆: 会话短期 / 画像长期 / 反馈强化      │
├─────────────────────────────────────────────────┤
│  模型层    LLM provider 抽象 (llm/)               │
│            默认火山方舟(豆包) ← OpenAI 协议兼容     │
└─────────────────────────────────────────────────┘
```

分层依赖规则（强制）：**上层可依赖下层，禁止反向**。`core` 不 import `api`；`agents` 不直接依赖 `profile` 的存储实现（通过注入的接口访问）。

## 目录 ↔ 架构对应

| 目录 | 职责 | 详细设计 |
|---|---|---|
| `src/yk_agent/api/` | HTTP/SSE 接口、鉴权、会话管理入口 | `08-api-spec.md` |
| `src/yk_agent/core/` | Orchestrator/Planner/State/Critic/护栏 | `03-agent-orchestration.md` ⭐ |
| `src/yk_agent/agents/` | 子智能体实现与 Registry | `03-agent-orchestration.md` |
| `src/yk_agent/skills/` | 技能包（prompt 资产 + 流程知识） | `06-skills-spec.md` |
| `src/yk_agent/mcp/` | 外部工具（地图/天气…）的 MCP 封装 | `07-mcp-tools.md` |
| `src/yk_agent/profile/` | 三层画像、偏好抽取、记忆回写 | `04-user-profile.md` |
| `src/yk_agent/knowledge/` | RAG：文档灌入、向量检索 | `04/05 文档` |
| `src/yk_agent/llm/` | provider 抽象：chat/embedding 统一接口 | 本文档 §模型接入 |

## 一次攻略请求的端到端链路

```
用户消息 (api/)
  → 载入会话 + 用户画像 (profile/)
  → Orchestrator: 意图理解 + 偏好抽取增量 (core/)
  → Planner: 生成/修订任务计划 (core/)
  → 派发子智能体（无依赖则并行）(core/ → agents/)
        子智能体内部: 调 MCP 拿实时数据 / 调 knowledge/ 检索
  → 汇总 Blackboard → 生成攻略（加载 trip-planner skill）
  → Critic 评审（行程合理性/画像匹配度）→ 不合格回炉
  → SSE 流式输出 (api/)
  → 回写: 画像增量 + 会话记忆 + agent trace (profile/ + storage)
```

## 技术选型及理由（摘要）

| 项 | 选型 | 一句话理由 | 详见 |
|---|---|---|---|
| 语言 | Python 3.12 | 智能体/数据生态最全，瓶颈在 LLM 延迟不在语言 | ADR-001 |
| 编排框架 | LangGraph | Send API 支持运行时动态并行派发；checkpoint 支持持久化与 human-in-the-loop | ADR-001 |
| API | FastAPI + sse-starlette | 异步原生、SSE 一等支持 | — |
| 主存储 | **SQLite**（aiosqlite + WAL） | 全环境统一：零运维、单机部署、文件即备份 | `05-data-model.md`、ADR-002 |
| 缓存 | 进程内存 | 会话热数据；SQLite 落库兜底 | `05-data-model.md` |
| LLM | 火山方舟(豆包)默认 | 国内可用、OpenAI 协议兼容 | 本文档 §模型接入 |

## 模型接入层（llm/）

统一两个接口，屏蔽厂商差异：

```python
class LLMProvider(Protocol):
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        json_mode: bool = False,
        **sampling,
    ) -> ChatResult: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- 默认 provider：火山方舟（OpenAI 协议兼容，`base_url` 指向方舟 endpoint）。
- **业务代码禁止直接 import 厂商 SDK**，统一经 `llm/` 的工厂函数获取 provider。
- 模型名、采样参数、温度等从配置（环境变量/settings）读取，不写死在代码里。
- 需要结构化输出的地方统一走 `json_mode` + pydantic 校验（校验失败重试 1 次，仍失败降级）。

## 配置管理

- 全部配置经 `pydantic-settings` 从环境变量 / `.env` 读取（`yk_agent/config.py`），**统一 `YK_` 前缀**（与机器上的全局环境变量隔离），包括：`YK_ARK_API_KEY`、`YK_ARK_BASE_URL`、`YK_MODEL_CHAT`、`YK_MODEL_EMBEDDING`、`YK_DATABASE_URL`（SQLite，形如 `sqlite:///data/yk_agent.db`）。
- `.env` 不入库（已在 .gitignore）；提供 `.env.example` 模板。
