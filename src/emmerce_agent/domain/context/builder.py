"""Context packet + builder (domain algorithm, no LLM dependency)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable


class SourceType(str, Enum):
    SYSTEM = "system"
    MEMORY_WORKING = "memory_working"
    MEMORY_EPISODIC = "memory_episodic"
    MEMORY_SEMANTIC = "memory_semantic"
    HISTORY = "history"
    MCP = "mcp"
    TOOL = "tool"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 1.5))


@dataclass(slots=True)
class ContextPacket:
    content: str
    token_count: int
    timestamp: datetime
    relevance_score: float
    importance: float
    source_type: str
    metadata: dict = field(default_factory=dict)
    packet_id: str = ""


@dataclass(slots=True)
class ContextConfig:
    max_tokens: int = 4096
    system_reserve_ratio: float = 0.2
    system_max_packets: int = 3
    min_relevance: float = 0.35
    w_relevance: float = 0.7
    w_recency: float = 0.3
    enable_compress: bool = True
    detail_top_n: int = 20
    heavy_compress: bool = False


@dataclass
class SelectLog:
    kept: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)


@dataclass
class StructuredContext:
    role_rules: str
    task: str
    evidence: str
    context: str
    total_tokens: int
    select_log: SelectLog

    def render(self) -> str:
        return (
            f"[Role&Rules]\n{self.role_rules}\n\n"
            f"[Task]\n{self.task}\n\n"
            f"[Evidence]\n{self.evidence}\n\n"
            f"[Context]\n{self.context}\n"
        )


def recency_score(ts: datetime, now: datetime | None = None) -> float:
    now = now or utcnow()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - ts).total_seconds() / 3600.0)
    return 1.0 / (1.0 + age_hours / 24.0)


class ContextBuilder:
    def __init__(self, config: ContextConfig | None = None):
        self.config = config or ContextConfig()
        self.last_log = SelectLog()

    def gather(self, *groups: Iterable[ContextPacket]) -> list[ContextPacket]:
        packets: list[ContextPacket] = []
        for group in groups:
            packets.extend(list(group))
        for i, p in enumerate(packets):
            if not p.packet_id:
                p.packet_id = f"pkt_{i}_{p.source_type}"
            if p.token_count <= 0:
                p.token_count = estimate_tokens(p.content)
        return packets

    def _score(self, p: ContextPacket, now: datetime | None = None) -> float:
        return (
            p.relevance_score * self.config.w_relevance
            + recency_score(p.timestamp, now) * self.config.w_recency
        ) * p.importance

    def select(self, packets: list[ContextPacket], *, now: datetime | None = None) -> list[ContextPacket]:
        cfg = self.config
        log = SelectLog()
        system_all = [p for p in packets if p.source_type == SourceType.SYSTEM.value]
        business = [p for p in packets if p.source_type != SourceType.SYSTEM.value]

        # System packets also consume budget — keep highest-importance within caps
        system_sorted = sorted(system_all, key=lambda p: p.importance, reverse=True)
        system_budget = int(cfg.max_tokens * cfg.system_reserve_ratio)
        kept_system: list[ContextPacket] = []
        sys_used = 0
        for p in system_sorted:
            if len(kept_system) >= cfg.system_max_packets:
                log.dropped.append(p.packet_id)
                log.reasons[p.packet_id] = "system_packet_cap"
                continue
            if sys_used + p.token_count > system_budget and kept_system:
                log.dropped.append(p.packet_id)
                log.reasons[p.packet_id] = "system_token_budget"
                continue
            kept_system.append(p)
            sys_used += p.token_count
            log.kept.append(p.packet_id)

        # Always keep at least one system packet if present
        if not kept_system and system_sorted:
            kept_system = [system_sorted[0]]
            log.kept.append(system_sorted[0].packet_id)
            sys_used = system_sorted[0].token_count

        remaining = max(0, cfg.max_tokens - sys_used)

        scored: list[tuple[float, ContextPacket]] = []
        for p in business:
            if p.relevance_score < cfg.min_relevance:
                log.dropped.append(p.packet_id)
                log.reasons[p.packet_id] = "below_min_relevance"
                continue
            scored.append((self._score(p, now), p))

        def sort_key(item: tuple[float, ContextPacket]) -> tuple:
            score, p = item
            protect = 0
            if p.source_type == SourceType.MEMORY_SEMANTIC.value:
                protect = 2
            elif p.importance >= 2.0 or p.metadata.get("starred"):
                protect = 1
            return (protect, score)

        scored.sort(key=sort_key, reverse=True)
        kept_biz: list[ContextPacket] = []
        used = 0
        for _, p in scored:
            if used + p.token_count <= remaining:
                kept_biz.append(p)
                used += p.token_count
                log.kept.append(p.packet_id)
            else:
                log.dropped.append(p.packet_id)
                log.reasons[p.packet_id] = "token_budget"
        self.last_log = log
        return kept_system + kept_biz

    def structure(self, packets: list[ContextPacket], task: str) -> StructuredContext:
        role_parts = [p.content for p in packets if p.source_type == SourceType.SYSTEM.value]
        evidence = [p.content for p in packets if p.source_type == SourceType.MEMORY_SEMANTIC.value]
        context_parts = [
            p.content
            for p in packets
            if p.source_type
            in {
                SourceType.MEMORY_WORKING.value,
                SourceType.MEMORY_EPISODIC.value,
                SourceType.HISTORY.value,
                SourceType.MCP.value,
                SourceType.TOOL.value,
            }
        ]
        role_rules = "\n".join(role_parts) or "你是电商数据分析助手。"
        evidence_text = "\n".join(evidence) or "(无)"
        context_text = "\n".join(context_parts) or "(无)"
        total = estimate_tokens(role_rules + task + evidence_text + context_text)
        return StructuredContext(
            role_rules=role_rules,
            task=task,
            evidence=evidence_text,
            context=context_text,
            total_tokens=total,
            select_log=self.last_log,
        )

    def compress(self, structured: StructuredContext, detail_lines: list[str] | None = None) -> StructuredContext:
        if not self.config.enable_compress or structured.total_tokens <= self.config.max_tokens:
            return structured
        ctx = structured.context
        if detail_lines:
            top_n = 5 if self.config.heavy_compress else self.config.detail_top_n
            summary = next((l for l in detail_lines if l.startswith("SUMMARY:")), "SUMMARY: (truncated)")
            detail_block = summary + "\n" + "\n".join(detail_lines[:top_n])
            if "<<<MCP_DETAIL>>>" in ctx:
                ctx = ctx.split("<<<MCP_DETAIL>>>")[0] + "<<<MCP_DETAIL>>>\n" + detail_block
            else:
                ctx = ctx + "\n" + detail_block
        render_tokens = estimate_tokens(structured.role_rules + structured.task + structured.evidence + ctx)
        if render_tokens > self.config.max_tokens:
            budget = max(
                200,
                self.config.max_tokens
                - estimate_tokens(structured.role_rules + structured.task + structured.evidence),
            )
            ctx = ctx[: int(budget * 1.5)] + "\n...(context compressed)"
        return StructuredContext(
            role_rules=structured.role_rules,
            task=structured.task,
            evidence=structured.evidence,
            context=ctx,
            total_tokens=estimate_tokens(structured.role_rules + structured.task + structured.evidence + ctx),
            select_log=structured.select_log,
        )

    def build(
        self,
        *,
        task: str,
        system: list[ContextPacket],
        memory: list[ContextPacket],
        semantic: list[ContextPacket],
        history: list[ContextPacket],
        tools: list[ContextPacket],
        detail_lines: list[str] | None = None,
    ) -> StructuredContext:
        gathered = self.gather(system, memory, semantic, history, tools)
        selected = self.select(gathered)
        structured = self.structure(selected, task)
        return self.compress(structured, detail_lines=detail_lines)
