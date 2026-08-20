"""Rough token budgeting for a single agent turn (chars/4 heuristic + tool payload)."""

from __future__ import annotations

import json
from typing import Any

from emmerce_agent.application.ports import LLMMessage, ToolResult


def estimate_text_tokens(text: str | None) -> int:
    if not text:
        return 0
    # Mixed CN/EN heuristic: ~2 chars ≈ 1 token for CJK-heavy text is closer,
    # but chars/4 is a conservative upper bound for budget enforcement.
    return max(1, (len(text) + 3) // 4)


def estimate_messages_tokens(messages: list[LLMMessage]) -> int:
    total = 0
    for m in messages:
        total += estimate_text_tokens(m.content)
        if m.tool_calls:
            total += estimate_text_tokens(json.dumps(m.tool_calls, ensure_ascii=False))
        if m.name:
            total += 2
    return total


def estimate_tool_result_tokens(result: ToolResult) -> int:
    payload: dict[str, Any] = {"data": result.data, "facts": result.numeric_facts}
    return estimate_text_tokens(json.dumps(payload, ensure_ascii=False, default=str))


class TurnTokenBudget:
    """Tracks cumulative estimated tokens within one chat turn."""

    def __init__(self, max_tokens: int):
        self.max_tokens = max(1, int(max_tokens))
        self.used = 0

    def add(self, n: int) -> None:
        self.used += max(0, n)

    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used)

    def would_exceed(self, n: int) -> bool:
        return self.used + n > self.max_tokens

    def ensure(self, n: int, *, message: str = "本轮分析资源已达上限，请缩小问题范围后重试") -> None:
        from emmerce_agent.domain.errors import TurnBudgetExceeded

        if self.would_exceed(n):
            raise TurnBudgetExceeded(message, used=self.used, limit=self.max_tokens)
        self.add(n)
