"""provider 工厂：业务代码获取模型能力的唯一入口。"""

from functools import lru_cache

from yk_agent.config import settings
from yk_agent.llm.provider import LLMProvider, OpenAICompatibleProvider


class ProviderNotConfigured(RuntimeError):
    """模型凭证未配置。提示信息面向开发者，指向 .env。"""


@lru_cache(maxsize=1)
def get_provider() -> LLMProvider:
    """进程内单例。未配置 ARK_API_KEY 时抛 ProviderNotConfigured——

    测试或离线场景请直接使用 llm.mock.MockLLMProvider，不要走本工厂。
    """
    if not settings.ark_api_key:
        raise ProviderNotConfigured(
            "ARK_API_KEY 未配置：请复制 .env.example 为 .env 并填写 ARK_API_KEY "
            "（火山方舟控制台 https://console.volcengine.com/ark 可创建）"
        )
    return OpenAICompatibleProvider(
        base_url=settings.ark_base_url,
        api_key=settings.ark_api_key,
        default_chat_model=settings.model_chat,
        default_embed_model=settings.model_embedding,
    )
