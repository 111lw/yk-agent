# 08 API 规范

> FastAPI 实现。MVP 只有一个核心对话接口 + 少量查询接口。所有接口前缀 `/api`，JSON in / JSON or SSE out。

## 接口清单

### 核心：对话（SSE 流式）

```
POST /api/chat
Body: { "session_id": "uuid" | null,   # null 则新建会话并在首事件返回
        "message": "想去云南玩5天，预算5000，不想爬山" }
```

SSE 事件流（`text/event-stream`），事件类型：

| event | data | 说明 |
|---|---|---|
| `session` | `{session_id, user_id}` | 首事件，总是最先发出 |
| `plan_update` | `{tasks: [{agent, instruction, depends_on}]}` | Planner 计划生成/修订时（自主编排对用户可视化） |
| `agent_start` / `agent_end` | `{agent, status}` | 子智能体派发开始/结束 |
| `confirmation_request` | `{agent, action, detail}` | 副作用动作等待确认（MVP 极少触发，机制必须存在） |
| `token` | `{text}` | 最终回答的流式 token |
| `done` | `{trip_id?, trace_id}` | 正常结束；有攻略产出时带 trip_id |
| `error` | `{code, message}` | 错误终止（错误码见下） |

### 其他接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat/confirm` | 确认/拒绝副作用动作 `{session_id, request_id, approved}`，恢复被中断的编排 |
| GET | `/api/profile` / PUT `/api/profile` | 查看/修正画像（用户可手动改，修正视为强信号回写） |
| GET | `/api/trips` / GET `/api/trips/{id}` | 历史攻略列表/详情 |
| POST | `/api/trips/{id}/feedback` | 攻略反馈 `{action: accept/modify/reject, detail?}`，进 L3 回写 |
| GET | `/healthz` | 健康检查（含 DB/Redis/LLM 连通性摘要） |

## 错误码

| code | 场景 |
|---|---|
| `RATE_LIMITED` | 限流 |
| `GUARDRAIL_LIMIT` | 护栏触发强制收敛（不算错误，照常输出 done，此码用于 V2 计费/统计预留） |
| `LLM_UNAVAILABLE` / `TOOL_UNAVAILABLE` | 模型/工具不可用 |
| `BAD_REQUEST` | 参数校验失败 |

## 约定

- 会话鉴权：MVP 用 header `X-User-Id`（匿名体系，见 05 文档 users 表）；接登录是 V2 的事，接口层预留依赖注入点。
- SSE 断线：客户端携 `session_id` + `Last-Event-ID` 重连，服务端从 checkpoint 恢复编排（LangGraph checkpoint，见 03 文档）。
- 所有响应中的 LLM 生成文本均为流式给出，非流式接口（trips/profile）直接读库。
- 接口变更必须同步本篇文档与 `api/` 实现。
