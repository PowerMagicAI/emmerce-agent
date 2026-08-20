"""Bounded, desensitized in-memory audit buffer (dev); production should ship to logging stack."""

from __future__ import annotations

from collections import deque
from typing import Any

from emmerce_agent.infrastructure.security.desensitize import desensitize_text


class AuditBuffer:
    """Rolling audit events with sensitive-field scrubbing."""

    SENSITIVE_KEYS = ("text", "user_text", "message", "content", "prompt")

    def __init__(self, maxlen: int = 2000):
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def append(self, event: dict[str, Any]) -> None:
        self._events.append(self._scrub(event))

    def find_by_trace(self, trace_id: str, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        out = []
        for e in self._events:
            if e.get("trace_id") != trace_id:
                continue
            if tenant_id is not None and e.get("tenant_id") not in (None, tenant_id):
                continue
            out.append(e)
        return out

    def __len__(self) -> int:
        return len(self._events)

    def _scrub(self, event: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for k, v in event.items():
            if k in self.SENSITIVE_KEYS and isinstance(v, str):
                cleaned[k] = desensitize_text(v).text
                cleaned[f"{k}_redacted"] = True
            else:
                cleaned[k] = v
        return cleaned
