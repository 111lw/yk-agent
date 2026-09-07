"""结构化输出助手：json_mode + pydantic 校验 + 失败重试 1 次。

docs/02-architecture.md §模型接入层约定：所有需要结构化输出的地方统一走本助手。
校验仍失败则抛 SchemaValidationError，由调用方决定降级（缺失数据优于脏数据）。
"""

import logging

from pydantic import BaseModel, ValidationError

from yk_agent.llm.models import ChatMessage
from yk_agent.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_RETRY_HINT = (
    "上一次输出未通过 JSON Schema 校验，错误如下：\n{err}\n"
    "请严格按照要求重新输出，只输出合法 JSON，不要包含任何解释性文字。"
)


class SchemaValidationError(RuntimeError):
    """重试后仍未产出合法结构化结果。"""


async def chat_validated[T: BaseModel](
    provider: LLMProvider,
    messages: list[ChatMessage],
    schema: type[T],
    *,
    model: str | None = None,
    **sampling,
) -> T:
    """调用 chat(json_mode=True) 并用 schema 校验，失败时带错误提示重试一次。"""
    conversation = list(messages)
    last_err: Exception | None = None

    for attempt in range(2):  # 首次 + 重试 1 次
        result = await provider.chat(conversation, model=model, json_mode=True, **sampling)
        try:
            return schema.model_validate_json(result.content)
        except ValidationError as e:
            last_err = e
            logger.warning("结构化输出校验失败（第 %d 次）: %s", attempt + 1, e)
            conversation = conversation + [
                ChatMessage(role="assistant", content=result.content),
                ChatMessage(role="user", content=_RETRY_HINT.format(err=e)),
            ]

    raise SchemaValidationError(f"结构化输出两次校验均失败: {last_err}") from last_err
