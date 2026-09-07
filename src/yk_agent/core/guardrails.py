"""编排护栏（硬规则，docs/03-agent-orchestration.md §护栏）。

触发后一律强制收敛：基于现有 findings 生成回答，绝不无限循环。
"""

from functools import lru_cache
from typing import Any

from yk_agent.config import get_settings

CRITIC_MAX_ROUNDS = 2  # Critic 回炉上限，超限带瑕疵输出并标注


@lru_cache(maxsize=1)
def _limits() -> tuple[int, int]:
    """护栏阈值从配置读取（测试可通过重建 settings 调整）；进程内只算一次。"""
    s = get_settings()
    return s.max_orchestration_steps, s.max_tokens_budget


def steps_exceeded(state: dict[str, Any]) -> bool:
    limit, _ = _limits()
    return state.get("steps_done", 0) >= limit


def tokens_exceeded(state: dict[str, Any]) -> bool:
    _, limit = _limits()
    return state.get("tokens_used", 0) >= limit


def critic_rounds_exhausted(state: dict[str, Any]) -> bool:
    return state.get("critic_rounds", 0) >= CRITIC_MAX_ROUNDS


def blocked_by_guardrail(state: dict[str, Any]) -> bool:
    """任一资源型护栏触发即强制收敛。"""
    return steps_exceeded(state) or tokens_exceeded(state)
