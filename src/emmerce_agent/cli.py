"""CLI: same tools as the Agent — pipeline / workflow / eval."""

from __future__ import annotations

import argparse
import json
import sys

from emmerce_agent.application.workflow.engine import WorkflowEngine
from emmerce_agent.domain.tenancy import TenantContext
from emmerce_agent.infrastructure.composition import build_container


def _tenant() -> TenantContext:
    return TenantContext("tenant_a", "cli", ("shop_a1", "shop_a2"), ("owner",), True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emmerce data production + analytics CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pipe = sub.add_parser("pipeline", help="抽取→分类→校验")
    p_pipe.add_argument("--shop", default="shop_a1")

    p_wf = sub.add_parser("workflow", help="命名工作流")
    p_wf.add_argument("name", choices=["product_qc", "ops_diagnosis", "ad_diagnosis"])
    p_wf.add_argument("--shop", default="shop_a1")

    p_an = sub.add_parser("anomaly", help="价格异常")
    p_an.add_argument("--shop", default="shop_a1")

    p_eval = sub.add_parser("eval", help="黄金集评测（默认 stub；--live 用 .env 模型）")
    p_eval.add_argument("--live", action="store_true", help="使用 EMMERCE_LLM_* 真实模型")

    args = parser.parse_args(argv)
    if args.cmd == "eval":
        from emmerce_agent.application.eval.runner import run_eval
        from emmerce_agent.infrastructure.config.settings import Settings
        from dataclasses import replace

        settings = Settings.from_env()
        if not args.live:
            settings = replace(settings, llm_provider="stub")
        report = run_eval(settings=settings)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.ok else 1

    c = build_container()
    tenant = _tenant()
    shop = getattr(args, "shop", "shop_a1")

    if args.cmd == "pipeline":
        out = c.gateway.execute(tenant, "run_product_pipeline", {"shop_id": shop}).data
        stats = out.get("stats")
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0 if int(stats.get("failed") or 0) >= 0 else 1
    if args.cmd == "workflow":
        result = WorkflowEngine(c.gateway.warehouse).run(args.name, tenant, shop)
        print(json.dumps(WorkflowEngine.to_dict(result), ensure_ascii=False, indent=2))
        return 0 if result.ok else 1
    if args.cmd == "anomaly":
        out = c.gateway.execute(tenant, "detect_price_anomaly", {"shop_id": shop}).data
        print(json.dumps({"anomaly_count": out.get("anomaly_count"), "anomalies": out.get("anomalies")}, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
