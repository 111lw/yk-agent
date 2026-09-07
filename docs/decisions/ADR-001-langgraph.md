# ADR-001：智能体框架选型 LangGraph

- 状态：已采纳
- 日期：2026-09-07
- 关联文档：`docs/02-architecture.md`、`docs/03-agent-orchestration.md`

## 背景

yk-agent 需要自主编排：Orchestrator 动态决定调用哪些子智能体、并行度、计划修订与终止；同时需要 human-in-the-loop（副作用确认）与完整 trace。

## 备选方案

| 方案 | 优势 | 弃用/采纳原因 |
|---|---|---|
| **LangGraph** | Send API 支持运行时动态并行派发（map-reduce）；Command 支持节点内决定跳转；Postgres checkpoint 原生支持中断恢复（副作用确认依赖此能力）；社区最大 | ✅ 采纳：动态并行 + checkpoint + 人工确认三项核心需求全部原生满足 |
| Claude Agent SDK | 内建 subagent/skill/MCP，起步快 | 自主派发策略不可深度定制；画像/评审闭环要顺着它的模式走；后续想换模型 provider 受限 |
| OpenAI Agents SDK | 轻量 | handoff 偏"转接"而非"编排"，并行控制弱 |
| Dify/Coze | 零代码验证快 | 平台锁定，画像系统与开放插件机制无法深度定制，不适合长期产品 |
| 自研 | 完全可控 | 需重造 checkpoint/中断恢复/并行派发，MVP 阶段成本不值 |

## 决策

采用 **LangGraph** 作为编排框架，配合以下模式：Plan-and-Execute（Orchestrator 先出结构化计划）、Send 动态并行派发、Blackboard 共享状态（TripState）、Postgres checkpoint。

## 后果

- 正面：护栏（步数/token 上限）、human-in-the-loop、断线恢复均有原生支撑；graph 拓扑与文档 03 中的设计一一对应，AI 生成代码一致性好。
- 负面：LangGraph 版本迭代快，API 有变动风险 → 升级需跑编排相关单测；学习成本略高 → 已由 03 文档的拓扑图与伪代码缓解。
- 子智能体未来以 MCP tool 暴露给第三方时，LangGraph 内部编排不受影响（封装在节点实现内）。
