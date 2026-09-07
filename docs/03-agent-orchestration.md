# 03 自主编排设计 ⭐

> 全项目最重要的文档。改动编排逻辑前必须读本篇；改动后必须同步本篇。

## 设计目标

智能体**自主决定**：任务如何拆解、调用哪些子智能体、以什么顺序（并行/串行）、何时修订计划、何时终止。即 **Plan-and-Execute + 动态派发 + 评审闭环**。

## 四个角色

```
                 ┌──────────────────┐
   用户请求 ──→  │   Orchestrator    │  唯一决策者：意图理解、规划、派发、汇总
                 │  (含 Planner 职能) │
                 └──┬────┬────┬─────┘
        读 Registry ↓    ↓ Send 并行派发   ↓ 汇总后送审
            ┌─────┐ ┌─────┐ ┌─────┐  ┌─────────┐
            │子Agent│ │子Agent│ │子Agent│ │  Critic  │
            └─────┘ └─────┘ └─────┘  └─────────┘
                    读写共享 Blackboard (TripState)
```

1. **Orchestrator（编排者）**：唯一持有全局视图的节点。职责：理解意图 → 生成/修订计划 → 按依赖派发子智能体 → 汇总产出 → 触发 Critic → 生成最终回复。
2. **SubAgent（子智能体）**：只做单一领域任务（如 POI 检索、路线串联、预算测算），**无全局视图**，只拿到任务描述 + 所需状态切片。子智能体之间**禁止互相调用**。
3. **Critic（评审者）**：独立节点，检查产出的行程合理性（距离/时间冲突/预算超支）与画像匹配度。不合格则带具体理由回到 Orchestrator 修订计划（最多 2 轮，超限带瑕疵输出并标注）。
4. **Blackboard（黑板）**：唯一共享状态 `TripState`，所有节点经它交换数据，禁止点对点传话。

## Agent Registry（注册表）

自主调用的前提是 Orchestrator 能"看见"每个子智能体。**所有子智能体必须经 Registry 注册，业务代码禁止硬编码调用**：

```python
# src/yk_agent/agents/registry.py
@dataclass(frozen=True)
class AgentSpec:
    name: str  # 如 "poi-agent"
    description: str  # 给 LLM 看的能力描述——质量直接决定编排质量，必须写清楚
    # 【能做什么/输入是什么/输出是什么/什么场景该选它】
    input_schema: type[BaseModel]  # pydantic 入参校验
    output_schema: type[BaseModel]  # pydantic 出参校验
    side_effect: bool = False  # 是否有副作用（True 则派发前必须人工确认）
    graph_node: str  # LangGraph 节点名
```

Orchestrator 的 system prompt 中注入 Registry 清单（name + description + input/output schema 摘要）。

## Blackboard：TripState（core/state.py）

```python
class TripState(TypedDict):
    # —— 只读上下文（Orchestrator 注入，子智能体不可修改）——
    session_id: str
    user_id: str
    user_profile: UserProfile  # 画像切片（见 04 文档）
    user_message: str
    # —— 编排控制 ——
    plan: list[PlanTask]  # 当前计划，Orchestrator 可修订
    critic_verdict: CriticVerdict | None
    steps_done: int  # 护栏计数
    # —— 产出累积 ——
    findings: dict[str, AgentFinding]  # key=agent name，各子智能体结构化产出
    final_answer: str | None
    messages: Annotated[list, add_messages]  # Orchestrator 的推理消息历史


class PlanTask(BaseModel):
    agent: str  # Registry 中的 name
    instruction: str  # 具体任务描述（含依赖产出如何使用）
    depends_on: list[str]  # 依赖的 agent name 列表（去重后无依赖 → 并行派发）
```

## 执行规则（Orchestrator 必须遵守）

1. **计划先行**：先输出结构化 `plan`（JSON，经 pydantic 校验），再执行；不允许走一步看一步地"顺手"调子智能体。
2. **并行派发**：`depends_on` 为空的任务用 LangGraph `Send` 并行派发；其余任务等上游完成后派发。
3. **计划可修订**：每批任务完成后 Orchestrator 检查 `findings`，可以（且应该）修改剩余计划——如天气子智能体返回暴雨 → 插入"室内替代方案"任务。修订即重写 `plan`。
4. **结构化产出**：子智能体输出必须通过其 `output_schema` 校验，写入 `findings`；校验失败重试 1 次，仍失败则记为该任务失败（缺失数据优于脏数据）。
5. **产出不回流全文**：子智能体的原始返回（如完整 POI 列表）不塞回 Orchestrator 消息历史，只留 `findings` 的结构化摘要——防止上下文爆炸。
6. **终止条件**：计划全部完成 → 送 Critic；Critic 通过 → 生成 `final_answer`。

## 护栏（硬规则，core/guardrails.py 实现）

| 规则 | 值 | 触发后行为 |
|---|---|---|
| 最大步数 | `steps_done <= 15` | 强制收敛：基于现有 findings 生成回答 |
| 单次编排 token 预算 | 配置项 `MAX_TOKENS_BUDGET` | 同上 |
| Critic 回炉次数 | ≤ 2 | 超限输出并附加"以下方面可能有瑕疵"说明 |
| 副作用动作 | `side_effect=True` 的任务 | **中断，SSE 发 `confirmation_request` 事件，等用户确认后才派发** |
| 领域边界 | 非旅游意图 | 礼貌拒答，不派发任何子智能体 |
| 失败降级 | 子智能体失败/超时 | 该项产出标记缺失，回答中说明，不阻塞整体 |

## 可观测性

每次编排写一条完整 trace（表 `agent_traces`，见 05 文档）：plan 快照、每次派发（agent/输入摘要/token/耗时）、Critic 结论。没有 trace 无法调试自主系统——**新增子智能体必须落 trace**。

## LangGraph 拓扑（MVP）

```
START → orchestrator ──(plan 有待派发且无依赖)──→ Send×N → 子智能体节点群
              ↑                                        │
              │──(critic 不通过, 回炉<2)── critic ←──────┘
              └──(全部完成)──→ responder(生成 final_answer) → END
              └──(护栏触发)──→ responder → END
```

- 子智能体注册时在 graph 上挂节点；Registry 是编译 graph 的输入之一。
- 状态持久化用 LangGraph checkpoint（Postgres saver），支持 human-in-the-loop 中断恢复。

## MVP 子智能体清单

| name | 职责 | 依赖工具 | side_effect |
|---|---|---|---|
| `poi-agent` | 按城市+偏好检索景点/餐厅/酒店候选 | map-mcp, knowledge | false |
| `route-agent` | 把 POI 串联成逐日行程（地理/时间合理性） | map-mcp(route) | false |
| `budget-agent` | 行程预算测算（交通/住宿/门票/餐饮分项） | knowledge | false |

> 天气接入为 V2；新增子智能体的流程：实现 → 注册 Registry → 写 description → 补 trace → 加单测。
