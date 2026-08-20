"""Validate that assistant-facing metric values are grounded in tool results."""

from __future__ import annotations

import re
from typing import Any

from emmerce_agent.application.ports import ToolResult
from emmerce_agent.domain.errors import HallucinationDetected
from emmerce_agent.domain.messaging import MessageBlock


_NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w.])")
_DATE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?)?"
)


class ResultValidator:
    """
    Production guardrail:
    - Any MessageBlock of type=metric must appear in tool numeric_facts
    - Free-text large money-like numbers should also be subset of known facts (soft/hard configurable)
    """

    def __init__(self, *, strict_text_numbers: bool = True):
        self.strict_text_numbers = strict_text_numbers

    def collect_facts(self, tool_results: list[ToolResult]) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for tr in tool_results:
            if tr.ok:
                facts.extend(tr.numeric_facts)
        return facts

    def assert_blocks_grounded(self, blocks: list[MessageBlock], tool_results: list[ToolResult]) -> None:
        facts = self.collect_facts(tool_results)
        known_pairs = {(f.get("metric_code"), self._norm(f.get("value"))) for f in facts}
        known_values = {self._norm(f.get("value")) for f in facts}

        for b in blocks:
            if b.type == "metric":
                key = (b.metric_code, self._norm(b.value))
                if key not in known_pairs and self._norm(b.value) not in known_values:
                    raise HallucinationDetected(
                        f"指标块未在工具结果中找到: {b.metric_code}={b.value}"
                    )

        if self.strict_text_numbers:
            for b in blocks:
                if b.type != "text" or not b.content:
                    continue
                if "口径说明" in b.content:
                    continue
                scanned = _DATE_RE.sub(" ", b.content)
                for m in _NUMBER_RE.finditer(scanned):
                    raw = m.group(1).replace(",", "")
                    try:
                        val = float(raw)
                    except ValueError:
                        continue
                    if val < 100:
                        continue
                    if self._norm(val) not in known_values:
                        raise HallucinationDetected(f"文本数值无法追溯到工具结果: {val}")

    @staticmethod
    def _norm(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            return None
