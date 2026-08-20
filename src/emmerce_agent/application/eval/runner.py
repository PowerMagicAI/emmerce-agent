"""Golden-set runner: stub (CI) or live LLM (opt-in)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from emmerce_agent.domain.tenancy import TenantContext
from emmerce_agent.infrastructure.composition import AppContainer, build_container
from emmerce_agent.infrastructure.config.settings import Settings


def default_golden_path() -> Path:
    return Path(__file__).resolve().parents[4] / "eval" / "golden_tools.json"


@dataclass
class CaseResult:
    id: str
    ok: bool
    tools: list[str]
    detail: str = ""
    metric_value: float | None = None


@dataclass
class EvalReport:
    provider: str
    model: str
    passed: int = 0
    failed: int = 0
    results: list[CaseResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "passed": self.passed,
            "failed": self.failed,
            "total": self.passed + self.failed,
            "ok": self.failed == 0,
            "results": [r.__dict__ for r in self.results],
        }


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    raw = json.loads((path or default_golden_path()).read_text(encoding="utf-8"))
    return list(raw.get("cases") or [])


def run_eval(
    *,
    container: AppContainer | None = None,
    settings: Settings | None = None,
    path: Path | None = None,
    tenant: TenantContext | None = None,
) -> EvalReport:
    c = container or build_container(settings)
    tenant = tenant or TenantContext(
        "tenant_a", "user_a_owner", ("shop_a1", "shop_a2"), ("owner",), True
    )
    report = EvalReport(provider=c.settings.llm_provider, model=c.settings.llm_model)
    for case in load_cases(path):
        ses = c.agent.create_session(tenant, shop_id="shop_a1")
        resp = c.agent.chat(ses.session_id, case["query"], shop_id="shop_a1")
        tools = [t.get("name") or "" for t in (resp.tool_traces or [])]
        expect = list(case.get("expect_tools") or [])
        tool_ok = (not expect) or any(t in tools for t in expect)
        metric_ok = True
        metric_value = None
        expect_metric = case.get("expect_metric")
        if expect_metric is not None:
            hits = [
                b
                for b in resp.blocks
                if b.type == "metric" and b.metric_code == expect_metric
            ]
            if not hits:
                metric_ok = False
            else:
                metric_value = hits[0].value
                if "expect_value" in case and round(float(hits[0].value or 0), 4) != round(
                    float(case["expect_value"]), 4
                ):
                    metric_ok = False
        ok = tool_ok and metric_ok and resp.status in {"completed", "awaiting_clarification"}
        detail = ""
        if not tool_ok:
            detail = f"tools={tools} expect={expect}"
        elif not metric_ok:
            detail = f"metric {expect_metric}={metric_value} expect={case.get('expect_value')}"
        report.results.append(
            CaseResult(id=case.get("id") or case["query"][:20], ok=ok, tools=tools, detail=detail, metric_value=metric_value)
        )
        if ok:
            report.passed += 1
        else:
            report.failed += 1
    return report
