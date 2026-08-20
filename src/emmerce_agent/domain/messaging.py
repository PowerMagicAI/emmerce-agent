"""Frontend/backend message protocol (PRD §8.3)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BlockType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    METRIC = "metric"
    FILE = "file"
    CITATION = "citation"
    CLARIFICATION = "clarification"
    WARNING = "warning"
    ERROR = "error"
    STEP = "step"


@dataclass(slots=True)
class MessageBlock:
    type: str
    content: str | None = None
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    metric_code: str | None = None
    value: float | int | None = None
    unit: str | None = None
    name: str | None = None
    url: str | None = None
    kind: str | None = None
    title: str | None = None
    id: str | None = None
    question: str | None = None
    options: list[str] | None = None
    actions: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(slots=True)
class ResponseMeta:
    data_as_of: str
    shops: list[str]
    channels: list[str]
    model: str
    trace_id: str
    tenant_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(slots=True)
class AgentTurnResult:
    session_id: str
    run_id: str
    status: str
    blocks: list[MessageBlock] = field(default_factory=list)
    meta: ResponseMeta | None = None
    tool_traces: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "status": self.status,
            "blocks": [b.to_dict() for b in self.blocks],
            "meta": self.meta.to_dict() if self.meta else None,
        }
