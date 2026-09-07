"""LLM 层数据模型：消息、调用结果。与 docs/02-architecture.md §模型接入层 对齐。"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ChatResult(BaseModel):
    """一次 chat 调用的结构化结果。raw 保留原始响应的关键字段便于排障，不参与业务逻辑。"""

    content: str
    finish_reason: str | None = None
    usage: ChatUsage = Field(default_factory=ChatUsage)
    model: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)
