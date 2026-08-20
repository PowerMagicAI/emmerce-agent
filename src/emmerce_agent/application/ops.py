"""Lightweight ops counters for data-production and tool health."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OpsCollector:
    tool_calls: int = 0
    tool_ok: int = 0
    tool_fail: int = 0
    schema_fail: int = 0
    llm_calls: int = 0
    token_est: int = 0
    last_pipeline_stats: dict[str, Any] | None = None
    by_tool: dict[str, dict[str, Any]] = field(default_factory=lambda: defaultdict(_tool_bucket))

    def record_schema_fail(self, tool: str) -> None:
        self.schema_fail += 1
        self.tool_calls += 1
        self.tool_fail += 1
        bucket = self.by_tool[tool]
        bucket["fail"] += 1
        bucket["schema_fail"] += 1

    def record_tool(self, tool: str, *, ok: bool, duration_ms: float, error: str | None = None) -> None:
        self.tool_calls += 1
        if ok:
            self.tool_ok += 1
        else:
            self.tool_fail += 1
        bucket = self.by_tool[tool]
        bucket["ok" if ok else "fail"] += 1
        bucket["ms"].append(round(duration_ms, 2))
        if error:
            bucket["last_error"] = error

    def record_llm(self, *, token_est: int) -> None:
        self.llm_calls += 1
        self.token_est += max(0, token_est)

    def record_pipeline(self, stats: dict[str, Any]) -> None:
        self.last_pipeline_stats = dict(stats)

    def snapshot(self) -> dict[str, Any]:
        tools = {}
        for name, b in self.by_tool.items():
            ms = b.get("ms") or []
            tools[name] = {
                "ok": b.get("ok", 0),
                "fail": b.get("fail", 0),
                "schema_fail": b.get("schema_fail", 0),
                "avg_ms": round(sum(ms) / len(ms), 2) if ms else 0,
                "last_error": b.get("last_error"),
            }
        intercept = None
        if self.last_pipeline_stats:
            total = int(self.last_pipeline_stats.get("total") or 0)
            failed = int(self.last_pipeline_stats.get("failed") or 0)
            intercept = {
                "failed": failed,
                "total": total,
                "rate": round(failed / total, 4) if total else 0,
                "issue_counts": self.last_pipeline_stats.get("issue_counts") or {},
            }
        return {
            "tool_calls": self.tool_calls,
            "tool_ok": self.tool_ok,
            "tool_fail": self.tool_fail,
            "schema_fail": self.schema_fail,
            "tool_success_rate": round(self.tool_ok / self.tool_calls, 4) if self.tool_calls else None,
            "llm_calls": self.llm_calls,
            "token_est": self.token_est,
            "pipeline_intercept": intercept,
            "by_tool": tools,
        }


def _tool_bucket() -> dict[str, Any]:
    return {"ok": 0, "fail": 0, "schema_fail": 0, "ms": [], "last_error": None}
