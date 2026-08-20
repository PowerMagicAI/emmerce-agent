"""Prompt-injection detection (domain security)."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"忽略(之前|以上|所有)?.{0,10}(规则|指令|限制)", re.I),
    re.compile(r"(导出|下载|拉取).{0,20}(全平台|全部商家|所有租户|全站).{0,20}(订单|数据)", re.I),
    re.compile(r"(ignore|disregard).{0,20}(previous|above|all).{0,20}(rules|instructions)", re.I),
    re.compile(r"(system\s*prompt|开发者模式|jailbreak)", re.I),
)


@dataclass(frozen=True, slots=True)
class InjectionHit:
    matched: bool
    pattern: str | None = None


class PromptInjectionDetector:
    def __init__(self, patterns: tuple[re.Pattern[str], ...] | None = None):
        self.patterns = patterns or DEFAULT_PATTERNS

    def check(self, user_text: str) -> InjectionHit:
        text = user_text or ""
        for p in self.patterns:
            m = p.search(text)
            if m:
                return InjectionHit(matched=True, pattern=p.pattern)
        return InjectionHit(matched=False)

    def is_blocked(self, user_text: str) -> bool:
        return self.check(user_text).matched
