# yk-agent

个性化旅游推荐智能体 —— 根据用户性格、心理与喜好生成定制旅游攻略；支持 Skill / MCP / Plugin 三级扩展能力，核心编排由智能体自主决策。

## 快速开始

```bash
conda env create -f environment.yml   # 首次创建环境
conda activate yk-agent
pip install -e ".[dev]"
uvicorn yk_agent.api.main:app --reload
```

> 当前处于 MVP 开发阶段，完整设计见 [docs/](docs/)，开发协作规范见 [CLAUDE.md](CLAUDE.md)。

## 文档导航

- [产品概览](docs/01-product-overview.md)
- [总体架构](docs/02-architecture.md)
- [自主编排设计](docs/03-agent-orchestration.md) ⭐
- [用户画像系统](docs/04-user-profile.md)
- [数据模型](docs/05-data-model.md)
- [Skill 规范](docs/06-skills-spec.md)
- [MCP 工具设计](docs/07-mcp-tools.md)
- [API 规范](docs/08-api-spec.md)
- [路线图](docs/09-roadmap.md)
- [技术决策记录 (ADR)](docs/decisions/)
