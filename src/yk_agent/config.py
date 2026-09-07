"""全局配置：全部经 pydantic-settings 从环境变量 / .env 读取。

设计说明见 docs/02-architecture.md §配置管理；字段与 .env.example 一一对应。
pydantic-settings 大小写不敏感：环境变量 ARK_API_KEY ↔ 字段 ark_api_key。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env 里多余的字段不报错，方便渐进加配置
    )

    # —— 存储 ——
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/yk_agent"
    redis_url: str = "redis://localhost:6379/0"

    # —— 模型（火山方舟，OpenAI 协议兼容）——
    ark_api_key: str = ""  # 留空表示未配置，get_provider() 会给出明确报错
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    model_chat: str = "doubao-seed-1-6-250615"
    model_embedding: str = "doubao-embedding-text-240715"

    # —— 外部工具 ——
    amap_api_key: str = ""  # 地图服务（MVP 二选一，见 docs/07-mcp-tools.md）

    # —— 编排护栏（docs/03-agent-orchestration.md）——
    max_orchestration_steps: int = 15
    max_tokens_budget: int = 200_000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例；测试里如需覆盖配置，monkeypatch 后调用 get_settings.cache_clear()。"""
    return Settings()


# 惯例导出：业务代码直接 from yk_agent.config import settings
settings = get_settings()
