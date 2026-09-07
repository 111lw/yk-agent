# 06 Skill 规范

> Skill = 给 LLM 的「领域知识 + 方法论」包，是 prompt 资产的工程化。产品迭代的主要方式就是加/改 skill。

## 与 SubAgent / MCP 的分工

| 机制 | 本质 | 例子 |
|---|---|---|
| **Skill** | 知识与流程（prompt 层），无独立执行 | 攻略生成方法论、冷启动问卷话术 |
| **SubAgent** | 可被编排调用的执行单元（有自己的 LLM 循环） | poi-agent、route-agent |
| **MCP** | 外部数据/能力（工具调用） | map-mcp、weather-mcp |

## 目录规范

```
src/yk_agent/skills/
└── trip-planner/                # skill 名 = 目录名（kebab-case）
    ├── SKILL.md                 # ⭐ 必需，见下
    ├── templates.md             # 可选：输出模板/预算表模板
    └── examples/                # 可选：few-shot 示例
```

## SKILL.md 格式

```markdown
---
name: trip-planner            # 与目录名一致
description: 生成个性化旅游攻略。当需要产出完整行程规划（逐日安排、住宿、
  美食、预算）时加载。                       # ⭐ 触发描述，Orchestrator 据此决定是否装载
---

## 方法论
（分步骤写清楚产出这份技能成果的流程……）

## 输出要求
（结构、长度、必须包含/禁止包含的内容……）

## 边界
（什么情况下本技能不适用、应交还给 Orchestrator……）
```

## 加载机制

- Orchestrator 在规划阶段拿到所有 skill 的 `name + description` 清单，决定为当前任务装载哪些 skill（MVP 规则：意图匹配 + 白名单兜底，V2 可换成语义路由）。
- 装载 = 将 SKILL.md 正文注入执行该任务的 prompt（子智能体或 Orchestrator 生成段）。
- 单次任务装载 skill ≤ 2 个，优先 description 匹配度高的。

## 编写守则

1. **description 决定触发**，写"什么时候需要我"，不写"我是什么"。
2. Skill 是方法论不是数据：景点列表属于知识库(kb)，"如何编排一日行程"才属于 skill。
3. 每个 skill 必须含「边界」段，防止越界输出。
4. Skill 改动必须附带一个 before/after 的对照用例（放 examples/ 或单测），防止回归。

## MVP 技能清单

| name | 触发场景 | 说明 |
|---|---|---|
| `trip-planner` | 生成完整攻略 | 行程编排方法论：逐日节奏、动线、预算表、替代方案；输出结构遵循 08 文档的 trip schema |
| `cold-start-questionnaire` | 新用户首次对话 | 3~5 轮引导式画像问卷的话术与追问策略（见 04 文档） |
| `trip-adjust` | 用户修改已有攻略 | 局部重排原则：最小改动、保持整体动线合理、修改点回写偏好 |

> 新增 skill 流程：建目录 → 写 SKILL.md → 在本清单登记 → 若影响编排触发，同步 `03-agent-orchestration.md`。
