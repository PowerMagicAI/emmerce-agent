"""Compose MessageBlocks from tool results + LLM text (no hardcoded tool-name branches in orchestrator)."""

from __future__ import annotations

from emmerce_agent.application.ports import ToolResult
from emmerce_agent.domain.messaging import BlockType, MessageBlock


def _clean_str(value: object | None, default: str = "") -> str:
    if value is None:
        return default
    text = str(value)
    return default if text == "None" else text


class BlockComposer:
    def __init__(self, *, data_as_of: str, include_口径_hint: bool = True):
        self.data_as_of = data_as_of
        self.include_口径_hint = include_口径_hint
        self._口径_emitted_sessions: set[str] = set()

    def compose(
        self,
        *,
        session_id: str,
        content: str,
        tool_results: list[ToolResult],
        emit_口径_hint: bool | None = None,
    ) -> list[MessageBlock]:
        blocks: list[MessageBlock] = []

        for tr in tool_results:
            if not tr.ok:
                continue
            # Prefer tool-provided blocks (open/closed)
            if tr.blocks:
                blocks.extend(tr.blocks)
                continue
            # Fallback: numeric facts only
            for fact in tr.numeric_facts:
                code = fact.get("metric_code")
                value = fact.get("value")
                if code is None or value is None:
                    continue
                blocks.append(
                    MessageBlock(
                        type=BlockType.METRIC.value,
                        metric_code=_clean_str(code),
                        value=value if isinstance(value, (int, float)) else None,
                        unit=_clean_str(fact.get("unit")),
                        content=_clean_str(fact.get("label")),
                    )
                )

        if content and content.strip():
            blocks.append(MessageBlock(type=BlockType.TEXT.value, content=content.strip()))
        if not blocks:
            blocks.append(MessageBlock(type=BlockType.TEXT.value, content="未获取到可用数据。"))

        should_hint = self.include_口径_hint if emit_口径_hint is None else emit_口径_hint
        if should_hint and session_id not in self._口径_emitted_sessions:
            blocks.append(
                MessageBlock(
                    type=BlockType.TEXT.value,
                    content=f"口径说明：标准指标以工具计算为准；数据截至 {self.data_as_of}",
                )
            )
            self._口径_emitted_sessions.add(session_id)
        return blocks
