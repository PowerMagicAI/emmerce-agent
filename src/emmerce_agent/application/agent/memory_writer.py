"""Episodic memory writer — secondary path; never fail the user turn."""

from __future__ import annotations

import logging
import re

from emmerce_agent.application.ports import EpisodicMemoryPort, EpisodicRecord, ToolResult
from emmerce_agent.domain.context import utcnow
from emmerce_agent.domain.messaging import MessageBlock

logger = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")


class EpisodicMemoryWriter:
    def __init__(self, episodic: EpisodicMemoryPort):
        self.episodic = episodic

    def maybe_write(
        self,
        *,
        tenant_id: str,
        user_id: str,
        shop_ids: list[str],
        user_text: str,
        blocks: list[MessageBlock],
        tool_results: list[ToolResult],
        data_as_of: str,
        feedback_blocked: bool,
        cancelled: bool,
        writes_blocked: bool,
    ) -> None:
        if cancelled or writes_blocked or feedback_blocked:
            return

        ok_tools = [tr for tr in tool_results if tr.ok]
        if not ok_tools:
            return

        has_numeric = any(tr.numeric_facts for tr in ok_tools)
        has_knowledge = any(
            tr.name in {"search_metric_knowledge", "search_episodic_memory"} and (tr.data.get("hits") or [])
            for tr in ok_tools
        )
        text_conclusion = next(
            (
                b.content
                for b in blocks
                if b.type == "text" and b.content and "口径说明" not in b.content
            ),
            "",
        )
        if not has_numeric and not (has_knowledge and text_conclusion and len(text_conclusion) >= 12):
            return

        metrics = [
            str(f["metric_code"])
            for tr in ok_tools
            for f in tr.numeric_facts
            if f.get("metric_code")
        ]
        confidence = self._confidence(ok_tools, has_numeric=has_numeric)
        trusted = confidence >= 0.55 and all(
            tr.ok for tr in tool_results if tr.name != "ask_clarification"
        )
        topic = self._topic(user_text, metrics, text_conclusion)
        importance = self._importance(
            has_numeric=has_numeric,
            has_knowledge=has_knowledge,
            metrics=metrics,
            confidence=confidence,
            conclusion=text_conclusion,
            tool_count=len(ok_tools),
        )

        try:
            self.episodic.write(
                EpisodicRecord(
                    id="",
                    tenant_id=tenant_id,
                    user_id=user_id,
                    shop_ids=list(shop_ids) or [],
                    topic=topic,
                    time_range="session",
                    metrics=metrics,
                    conclusion=text_conclusion or "分析完成",
                    confidence=confidence,
                    data_as_of=data_as_of,
                    importance=importance,
                    trusted=trusted,
                    created_at=utcnow(),
                )
            )
        except Exception:  # noqa: BLE001 — memory must not break main turn
            logger.exception("episodic memory write failed; ignored")

    @staticmethod
    def _topic(user_text: str, metrics: list[str], conclusion: str) -> str:
        """Extractive short title — prefer conclusion lead + metric tags over raw truncation."""
        lead = ""
        if conclusion:
            # First clause / sentence as summary title
            for sep in ("。", "；", ";", "\n", "！", "!"):
                if sep in conclusion:
                    lead = conclusion.split(sep, 1)[0].strip()
                    break
            if not lead:
                lead = conclusion.strip()
            lead = _WHITESPACE.sub(" ", lead)
            if len(lead) > 36:
                lead = lead[:33] + "..."
        if not lead:
            base = _WHITESPACE.sub(" ", user_text.strip())
            lead = (base[:33] + "...") if len(base) > 36 else base
        if metrics:
            tag = ",".join(metrics[:2])
            combined = f"{lead} [{tag}]"
            return combined[:48] if len(combined) > 48 else combined
        return lead or "分析记录"

    @staticmethod
    def _importance(
        *,
        has_numeric: bool,
        has_knowledge: bool,
        metrics: list[str],
        confidence: float,
        conclusion: str,
        tool_count: int,
    ) -> float:
        """Auto importance in [1.0, 2.4]; user star can still raise further."""
        score = 1.0
        if has_numeric:
            score += 0.35
        if has_knowledge:
            score += 0.2
        if len(metrics) >= 2:
            score += 0.15
        if confidence >= 0.8:
            score += 0.2
        if len(conclusion) >= 40:
            score += 0.1
        if tool_count >= 2:
            score += 0.1
        return round(min(score, 2.4), 2)

    @staticmethod
    def _confidence(ok_tools: list[ToolResult], *, has_numeric: bool) -> float:
        score = 0.45
        if has_numeric:
            score += 0.35
        if any(tr.name == "search_metric_knowledge" for tr in ok_tools):
            score += 0.1
        if any(tr.blocks for tr in ok_tools):
            score += 0.05
        return round(min(score, 0.95), 2)
