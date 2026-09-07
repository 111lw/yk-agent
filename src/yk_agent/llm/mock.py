"""Mock 实现：测试与离线开发用，不发起任何网络请求。"""

from typing import Any

from yk_agent.llm.models import ChatMessage, ChatResult
from yk_agent.llm.provider import LLMProvider


class MockLLMProvider(LLMProvider):
    """按脚本依次返回预设内容；脚本耗尽后返回默认占位串。

    embed 返回固定维度的零向量（维度可配，默认 4，测试够用）。
    """

    def __init__(
        self,
        chat_responses: list[str] | None = None,
        *,
        embed_dim: int = 4,
        default_response: str = "（mock 回复）",
    ) -> None:
        self.chat_responses = list(chat_responses or [])
        self.embed_dim = embed_dim
        self.default_response = default_response
        self.calls: list[dict[str, Any]] = []  # 记录调用入参，供测试断言

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        json_mode: bool = False,
        **sampling: Any,
    ) -> ChatResult:
        self.calls.append(
            {"messages": messages, "model": model, "json_mode": json_mode, **sampling}
        )
        content = self.chat_responses.pop(0) if self.chat_responses else self.default_response
        return ChatResult(content=content, model=model or "mock-model")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append({"embed": list(texts)})
        return [[0.0] * self.embed_dim for _ in texts]
