"""LLMProvider 抽象与 OpenAI 协议兼容实现（火山方舟默认走此实现）。

硬规则（CLAUDE.md）：业务代码禁止直接 import 厂商 SDK，一律经 factory.get_provider()。
"""

from abc import ABC, abstractmethod
from typing import Any

from openai import AsyncOpenAI

from yk_agent.llm.models import ChatMessage, ChatResult, ChatUsage

# 允许透传给厂商 API 的采样参数白名单——防拼写错误把垃圾参数发上线
_SAMPLING_ALLOWLIST = {
    "temperature",
    "top_p",
    "max_tokens",
    "presence_penalty",
    "frequency_penalty",
}


class LLMProvider(ABC):
    """模型接入统一接口。所有实现的公共行为约定：

    - chat 透传的采样参数只允许 _SAMPLING_ALLOWLIST 中的键；
    - embed 返回顺序与输入一一对应；
    - 网络/API 错误向上抛，由调用方决定降级策略（见 docs/03-agent-orchestration.md 护栏）。
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        json_mode: bool = False,
        **sampling: Any,
    ) -> ChatResult: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI 协议兼容实现。火山方舟 base_url 指向 ark endpoint 即可直接使用。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        default_chat_model: str,
        default_embed_model: str,
        client: AsyncOpenAI | None = None,  # 测试注入 mock 用
    ) -> None:
        self._client = client or AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._default_chat_model = default_chat_model
        self._default_embed_model = default_embed_model

    @staticmethod
    def _filter_sampling(sampling: dict[str, Any]) -> dict[str, Any]:
        unknown = set(sampling) - _SAMPLING_ALLOWLIST
        if unknown:
            raise ValueError(
                f"不支持的采样参数: {sorted(unknown)}，允许: {sorted(_SAMPLING_ALLOWLIST)}"
            )
        return {k: v for k, v in sampling.items() if v is not None}

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        json_mode: bool = False,
        **sampling: Any,
    ) -> ChatResult:
        kwargs: dict[str, Any] = {
            "model": model or self._default_chat_model,
            "messages": [m.model_dump() for m in messages],
            **self._filter_sampling(sampling),
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        return ChatResult(
            content=choice.message.content or "",
            finish_reason=choice.finish_reason,
            usage=ChatUsage(
                prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            ),
            model=resp.model,
            raw={"id": resp.id},
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self._client.embeddings.create(model=self._default_embed_model, input=texts)
        return [item.embedding for item in resp.data]
