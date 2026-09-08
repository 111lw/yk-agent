# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

**yk-agent** 是一个个性化旅游推荐智能体：通过用户画像（性格、心理、喜好）驱动，支持自主编排（智能体自行决定调用哪些子智能体、以何种顺序），能力通过 Skill（技能包）/ MCP（外部工具协议）/ Plugin（插件）三种机制扩展。

- 产品定位与边界：`docs/01-product-overview.md`
- 当前开发阶段：**MVP**（范围见 `docs/09-roadmap.md`，不要实现超出 MVP 范围的功能）

## 技术栈

| 项 | 选型 |
|---|---|
| 语言 | Python 3.12+，环境管理用 **conda**（见 `environment.yml`），依赖安装用 pip |
| 智能体框架 | LangGraph（决策记录见 `docs/decisions/ADR-001-langgraph.md`） |
| API | FastAPI + SSE 流式输出 |
| 存储 | **SQLite**（全环境，aiosqlite + WAL，决策见 `docs/decisions/ADR-002-sqlite.md`） |
| 模型接入 | 自研 provider 抽象层（`src/yk_agent/llm/`），默认火山方舟(豆包)，可切换 OpenAI/Claude；**业务代码禁止直接 import 任何厂商 SDK** |

## 常用命令

```bash
conda activate yk-agent                            # 激活环境（首次先 conda env create -f environment.yml）
pip install -e ".[dev]"                            # 以可编辑模式安装本项目（新加依赖后重跑）
pytest                                             # 跑全部测试
pytest tests/test_xxx.py -k "case_name"            # 跑单个测试
uvicorn yk_agent.api.main:app --reload             # 启动开发服务
python scripts/init_db.py                          # 初始化数据库
ruff check . && ruff format .                      # lint + format
```

## 文档地图（动手前必读）

| 你要做的事 | 先读 |
|---|---|
| 改编排逻辑（Orchestrator/Planner/子智能体派发） | `docs/03-agent-orchestration.md` ⭐ 全项目最重要文档 |
| 改画像/记忆相关 | `docs/04-user-profile.md` |
| 改表结构 / 写迁移 | `docs/05-data-model.md` + `src/yk_agent/storage/sqlite.py`（schema 事实来源） |
| 新增/修改 Skill | `docs/06-skills-spec.md` |
| 新增/修改 MCP 工具 | `docs/07-mcp-tools.md` |
| 改 API 接口 | `docs/08-api-spec.md` |
| 任何架构级决策 | `docs/decisions/` 下的 ADR，重大决策需新增 ADR |

## 编码规范

- 模块组织严格按 `src/yk_agent/` 下现有分包：`core`（编排）/ `agents`（子智能体）/ `skills` / `mcp` / `profile`（画像）/ `knowledge`（RAG）/ `llm`（模型抽象）/ `api`。不确定放哪时看各包 `__init__.py` 的职责说明。
- 所有跨层对象用 pydantic model；编排状态统一在 `core/state.py` 定义，禁止子智能体私自扩展状态字段。
- 子智能体必须通过 Agent Registry 注册（见 03 文档），禁止在代码里硬编码调用某个子智能体。
- 只读操作可自主并行派发；**一切有副作用的动作（下单/支付/发送）必须中断请求用户确认**，这条是硬规则。
- 注释和 docstring 用中文，命名用英文。注释只写"为什么"，不复述"做了什么"。
- 每个可独立测试的模块配 pytest 单测，测试文件放 `tests/`，命名 `test_<模块>.py`。

## 文档同步要求

设计变更必须同步文档，否则下次会话的 AI 会按旧文档生成不一致的代码：

- 改了编排规则 → 同步 `docs/03-agent-orchestration.md`
- 改了架构/选型 → 新增 ADR 到 `docs/decisions/`
- 接口/表结构变更 → 同步 08 / 05 文档及 `src/yk_agent/storage/sqlite.py`
