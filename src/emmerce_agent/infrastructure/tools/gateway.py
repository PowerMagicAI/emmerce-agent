"""Tool gateway: schema validate → RBAC → rate limit → dispatch → audit."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from emmerce_agent.application.ops import OpsCollector
from emmerce_agent.application.audit import AuditBuffer
from emmerce_agent.application.analytics.ads import summarize_ads
from emmerce_agent.application.analytics.alerts import alerts_to_dict, scan_alerts
from emmerce_agent.application.analytics.invalid_orders import flag_invalid_orders
from emmerce_agent.application.analytics.metrics import compute_metric
from emmerce_agent.application.analytics.price_anomaly import detect_price_anomalies
from emmerce_agent.application.analytics.sales_forecast import forecast_sales
from emmerce_agent.application.data_pipeline.ocr import fake_ocr
from emmerce_agent.application.data_pipeline.run import run_product_pipeline
from emmerce_agent.application.data_pipeline.vision import image_text_mismatch
from emmerce_agent.application.ports import (
    EpisodicMemoryPort,
    ExportStorePort,
    SemanticMemoryPort,
    ToolGatewayPort,
    ToolResult,
    WarehousePort,
)
from emmerce_agent.application.workflow.engine import WorkflowEngine
from emmerce_agent.domain.errors import (
    PermissionDenied,
    RateLimited,
    ToolExecutionError,
    ValidationFailed,
)
from emmerce_agent.domain.messaging import BlockType, MessageBlock
from emmerce_agent.domain.metrics.catalog import MetricCatalog
from emmerce_agent.domain.tenancy import TenantContext
from emmerce_agent.domain.tools.specs import ToolSpec, build_tool_specs
from emmerce_agent.domain.tools.validation import validate_json_schema
from emmerce_agent.infrastructure.security.desensitize import desensitize_text


@dataclass
class FeatureFlags:
    memory_enabled: bool = True
    rag_enabled: bool = True
    inventory_tool_enabled: bool = True
    order_tool_enabled: bool = True
    export_tool_enabled: bool = True
    analytics_tool_enabled: bool = True
    ads_tool_enabled: bool = True
    alert_tool_enabled: bool = True


@dataclass
class ToolCallLog:
    tenant_id: str
    tool: str
    params: dict[str, Any]
    duration_ms: float
    ok: bool
    error: str | None = None


class RateLimiter:
    def __init__(self, max_calls: int = 20, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, tenant_id: str) -> None:
        now = time.monotonic()
        q = self._hits[tenant_id]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            raise RateLimited()
        q.append(now)


Handler = Callable[[TenantContext, dict[str, Any]], ToolResult]


class ToolGateway(ToolGatewayPort):
    def __init__(
        self,
        *,
        catalog: MetricCatalog,
        warehouse: WarehousePort,
        episodic: EpisodicMemoryPort,
        semantic: SemanticMemoryPort,
        exports: ExportStorePort,
        flags: FeatureFlags | None = None,
        limiter: RateLimiter | None = None,
        data_as_of: str = "2026-08-04T08:00:00+08:00",
        max_retries: int = 2,
        audit_maxlen: int = 2000,
        log_maxlen: int = 5000,
        ops: OpsCollector | None = None,
    ):
        self.catalog = catalog
        self.warehouse = warehouse
        self.episodic = episodic
        self.semantic = semantic
        self.exports = exports
        self.flags = flags or FeatureFlags()
        self.limiter = limiter or RateLimiter()
        self.data_as_of = data_as_of
        self.max_retries = max_retries
        self.logs: deque[ToolCallLog] = deque(maxlen=log_maxlen)
        self.audit = AuditBuffer(maxlen=audit_maxlen)
        self.ops = ops or OpsCollector()
        self._specs = build_tool_specs(allowed_metric_codes=sorted(catalog.allowed_codes()))
        self._spec_index = {s.name: s for s in self._specs}
        self._handlers: dict[str, Handler] = {
            "query_metric": self._query_metric,
            "compare_metric": self._compare_metric,
            "query_slow_moving": self._query_slow_moving,
            "export_report": self._export_report,
            "ask_clarification": self._ask_clarification,
            "search_episodic_memory": self._search_episodic,
            "search_metric_knowledge": self._search_semantic,
            "run_product_pipeline": self._run_product_pipeline,
            "detect_price_anomaly": self._detect_price_anomaly,
            "flag_invalid_orders": self._flag_invalid_orders,
            "forecast_sales": self._forecast_sales,
            "run_workflow": self._run_workflow,
            "query_ad_performance": self._query_ad_performance,
            "run_ocr_check": self._run_ocr_check,
            "run_alert_scan": self._run_alert_scan,
            "list_alerts": self._list_alerts,
        }

    def list_specs(self) -> list[ToolSpec]:
        return list(self._specs)

    def execute(self, tenant: TenantContext, name: str, arguments: dict[str, Any]) -> ToolResult:
        spec = self._spec_index.get(name)
        if not spec:
            return ToolResult(ok=False, name=name, data={}, error_code="UNKNOWN_TOOL", error_message=f"未知工具 {name}")

        try:
            validate_json_schema(arguments, spec.parameters)
        except ValidationFailed as e:
            self.ops.record_schema_fail(name)
            return ToolResult(ok=False, name=name, data={}, error_code=e.code, error_message=e.message)

        handler = self._handlers.get(name)
        if not handler:
            return ToolResult(ok=False, name=name, data={}, error_code="NO_HANDLER", error_message="未实现")

        self.limiter.check(tenant.tenant_id)
        start = time.perf_counter()
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                result = handler(tenant, arguments)
                self.logs.append(
                    ToolCallLog(
                        tenant_id=tenant.tenant_id,
                        tool=name,
                        params=arguments,
                        duration_ms=(time.perf_counter() - start) * 1000,
                        ok=result.ok,
                        error=result.error_code,
                    )
                )
                dur = (time.perf_counter() - start) * 1000
                self.ops.record_tool(name, ok=result.ok, duration_ms=dur, error=result.error_code)
                if name == "run_product_pipeline" and result.ok:
                    self.ops.record_pipeline((result.data or {}).get("stats") or {})
                return result
            except RateLimited as e:
                self._ops_fail(name, start, e.code)
                raise e
            except PermissionDenied as e:
                self.logs.append(
                    ToolCallLog(tenant.tenant_id, name, arguments, (time.perf_counter() - start) * 1000, False, e.code)
                )
                self._ops_fail(name, start, e.code)
                return ToolResult(ok=False, name=name, data={}, error_code=e.code, error_message=e.message)
            except ToolExecutionError as e:
                last_err = e
                if not e.retryable or attempt >= self.max_retries:
                    msg = e.message
                    if "SELECT" in msg or "FROM" in msg:
                        msg = "数据查询超时，请稍后重试"
                    self.logs.append(
                        ToolCallLog(
                            tenant.tenant_id, name, arguments, (time.perf_counter() - start) * 1000, False, e.code
                        )
                    )
                    self._ops_fail(name, start, e.code)
                    return ToolResult(ok=False, name=name, data={}, error_code=e.code, error_message=msg)
            except Exception as e:  # noqa: BLE001 — boundary
                last_err = e
                break

        self._ops_fail(name, start, "TOOL_ERROR")
        return ToolResult(
            ok=False,
            name=name,
            data={},
            error_code="TOOL_ERROR",
            error_message=str(last_err) if last_err else "工具执行失败",
        )

    def _ops_fail(self, name: str, start: float, error: str | None) -> None:
        self.ops.record_tool(
            name, ok=False, duration_ms=(time.perf_counter() - start) * 1000, error=error
        )

    # —— handlers ——
    def _query_metric(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        if not self.flags.order_tool_enabled:
            raise ToolExecutionError("订单查询能力已降级关闭，请稍后重试或联系运营", code="TOOL_DISABLED")
        shop_id = args["shop_id"]
        metric_code = args["metric_code"]
        tenant.ensure_shop_access(shop_id)
        metric = self.catalog.require(metric_code)
        if metric_code in {"ad_spend", "ad_roi"}:
            if not self.flags.ads_tool_enabled:
                raise ToolExecutionError("广告分析能力已降级关闭", code="TOOL_DISABLED")
            ads = self.warehouse.query_ads(
                tenant_id=tenant.tenant_id,
                shop_id=shop_id,
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            summary = summarize_ads(ads)
            value = float(summary["spend"] if metric_code == "ad_spend" else summary["roi"])
            formula = "sum(ad.spend)" if metric_code == "ad_spend" else "ad_gmv / ad_spend"
        else:
            rows = self.warehouse.query_orders(
                tenant_id=tenant.tenant_id,
                shop_id=shop_id,
                date_from=args.get("date_from"),
                date_to=args.get("date_to"),
            )
            value, formula = compute_metric(metric_code, rows)

        data = {
            "metric_code": metric_code,
            "name": metric.name,
            "value": value,
            "unit": metric.unit,
            "data_as_of": self.data_as_of,
            "formula_applied": formula,
            "shop_id": shop_id,
            "version": metric.version,
        }
        facts = [
            {
                "metric_code": metric_code,
                "value": value,
                "unit": metric.unit,
                "label": f"{metric.name}={value}",
            }
        ]
        return ToolResult(
            ok=True,
            name="query_metric",
            data=data,
            numeric_facts=facts,
            blocks=[
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code=metric_code,
                    value=value,
                    unit=metric.unit,
                    content=f"{metric.name}={value}",
                )
            ],
        )

    def _compare_metric(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        if not self.flags.order_tool_enabled:
            raise ToolExecutionError("订单查询能力已降级关闭，请稍后重试或联系运营", code="TOOL_DISABLED")
        shop_id = args["shop_id"]
        metric_code = args["metric_code"]
        tenant.ensure_shop_access(shop_id)
        metric = self.catalog.require(metric_code)
        rows_a = self.warehouse.query_orders(
            tenant_id=tenant.tenant_id,
            shop_id=shop_id,
            date_from=args.get("date_from_a"),
            date_to=args.get("date_to_a"),
        )
        rows_b = self.warehouse.query_orders(
            tenant_id=tenant.tenant_id,
            shop_id=shop_id,
            date_from=args.get("date_from_b"),
            date_to=args.get("date_to_b"),
        )
        value_a, formula = compute_metric(metric_code, rows_a)
        value_b, _ = compute_metric(metric_code, rows_b)
        delta = round(float(value_b) - float(value_a), 4)
        delta_pct = None if value_a == 0 else round(delta / float(value_a), 4)
        data = {
            "metric_code": metric_code,
            "name": metric.name,
            "shop_id": shop_id,
            "period_a": {"date_from": args.get("date_from_a"), "date_to": args.get("date_to_a"), "value": value_a},
            "period_b": {"date_from": args.get("date_from_b"), "date_to": args.get("date_to_b"), "value": value_b},
            "value_a": value_a,
            "value_b": value_b,
            "delta": delta,
            "delta_pct": delta_pct,
            "unit": metric.unit,
            "formula_applied": formula,
            "data_as_of": self.data_as_of,
        }
        facts = [
            {"metric_code": metric_code, "value": value_a, "unit": metric.unit, "label": f"{metric.name}A={value_a}"},
            {"metric_code": metric_code, "value": value_b, "unit": metric.unit, "label": f"{metric.name}B={value_b}"},
            {"metric_code": f"{metric_code}_delta", "value": delta, "unit": metric.unit, "label": f"差值={delta}"},
        ]
        if delta_pct is not None:
            facts.append(
                {
                    "metric_code": f"{metric_code}_delta_pct",
                    "value": delta_pct,
                    "unit": "ratio",
                    "label": f"变动={delta_pct}",
                }
            )
        return ToolResult(
            ok=True,
            name="compare_metric",
            data=data,
            numeric_facts=facts,
            blocks=[
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code=metric_code,
                    value=value_b,
                    unit=metric.unit,
                    content=f"{metric.name} 区间B={value_b} 区间A={value_a} 差值={delta}",
                )
            ],
        )

    def _query_slow_moving(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        if not self.flags.inventory_tool_enabled:
            raise ToolExecutionError("库存分析能力已降级关闭，请稍后重试或联系运营", code="TOOL_DISABLED")
        shop_id = args["shop_id"]
        month = args["month"]
        include_detail = bool(args.get("include_detail", False))
        tenant.ensure_shop_access(shop_id)
        rows = self.warehouse.query_orders(tenant_id=tenant.tenant_id, shop_id=shop_id)
        items = [
            {"sku": r.sku or "UNKNOWN", "sold_qty": r.sold_qty, "stock_qty": r.stock_qty}
            for r in rows
            if r.stock_qty >= 50 and r.sold_qty <= 5
        ]
        summary = {"month": month, "slow_moving_count": len(items), "shop_id": shop_id}
        details = items if include_detail else []
        data = {"summary": summary, "details": details}
        table_rows: list[list[Any]]
        if details:
            table_rows = [[d.get("sku"), d.get("sold_qty"), d.get("stock_qty")] for d in details]
            columns = ["sku", "sold_qty", "stock_qty"]
        else:
            table_rows = [[summary.get("month"), summary.get("slow_moving_count"), summary.get("shop_id")]]
            columns = ["month", "slow_moving_count", "shop_id"]
        return ToolResult(
            ok=True,
            name="query_slow_moving",
            data=data,
            numeric_facts=[
                {
                    "metric_code": "slow_moving_count",
                    "value": float(len(items)),
                    "unit": "count",
                    "label": f"{month}滞销={len(items)}",
                }
            ],
            blocks=[
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code="slow_moving_count",
                    value=float(len(items)),
                    unit="count",
                    content=f"{month}滞销={len(items)}",
                ),
                MessageBlock(type=BlockType.TABLE.value, columns=columns, rows=table_rows),
            ],
        )

    def _export_report(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        if not self.flags.export_tool_enabled:
            raise ToolExecutionError("导出能力已关闭", code="TOOL_DISABLED")
        filename = args["filename"]
        rows = args.get("rows") or []
        if filename.startswith("ALL_TENANTS") or any(
            isinstance(r, dict) and r.get("tenant_id") and r["tenant_id"] != tenant.tenant_id for r in rows
        ):
            self.audit.append({"type": "HIGH_RISK_BLOCKED", "user": tenant.user_id, "name": filename})
            raise ToolExecutionError("禁止批量导出全平台订单", code="HIGH_RISK_BLOCKED")

        lines = [desensitize_text(str(r)).text for r in rows]
        content = ("\n".join(lines)).encode("utf-8")
        f = self.exports.create(
            tenant_id=tenant.tenant_id, user_id=tenant.user_id, name=filename, content=content
        )
        download_url = f"/api/v1/exports/{f.id}/download"
        return ToolResult(
            ok=True,
            name="export_report",
            data={
                "id": f.id,
                "name": f.name,
                "download_url": download_url,
                "expires_at": f.expires_at.isoformat(),
            },
            blocks=[
                MessageBlock(
                    type=BlockType.FILE.value,
                    name=f.name,
                    url=download_url,
                    content="报表已生成",
                )
            ],
        )

    def _ask_clarification(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, name="ask_clarification", data=args)

    def _search_episodic(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        if not self.flags.memory_enabled:
            return ToolResult(ok=True, name="search_episodic_memory", data={"hits": []})
        shop_id = args["shop_id"]
        tenant.ensure_shop_access(shop_id)
        hits = self.episodic.search(
            tenant_id=tenant.tenant_id,
            shop_ids=list(tenant.shop_ids),
            query=args["query"],
            limit=int(args.get("limit") or 3),
        )
        hit_rows = [
            {
                "id": r.id,
                "topic": r.topic,
                "conclusion": r.conclusion,
                "score": score,
                "data_as_of": r.data_as_of,
            }
            for score, r in hits
        ]
        return ToolResult(
            ok=True,
            name="search_episodic_memory",
            data={"hits": hit_rows},
            blocks=[
                MessageBlock(
                    type=BlockType.CITATION.value,
                    kind="episodic",
                    title=item.get("topic"),
                    id=item.get("id"),
                )
                for item in hit_rows
            ],
        )

    def _search_semantic(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        if not self.flags.rag_enabled:
            return ToolResult(ok=True, name="search_metric_knowledge", data={"hits": []})
        hits = self.semantic.search(args["query"], limit=int(args.get("limit") or 3))
        hit_rows = [
            {"id": d.id, "title": d.title, "content": d.content, "score": score}
            for score, d in hits
        ]
        return ToolResult(
            ok=True,
            name="search_metric_knowledge",
            data={"hits": hit_rows},
            blocks=[
                MessageBlock(
                    type=BlockType.CITATION.value,
                    kind="semantic",
                    title=item.get("title"),
                    id=item.get("id"),
                )
                for item in hit_rows
            ],
        )

    def _ensure_analytics(self) -> None:
        if not self.flags.analytics_tool_enabled:
            raise ToolExecutionError("分析/质检能力已降级关闭", code="TOOL_DISABLED")

    def _run_product_pipeline(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        self._ensure_analytics()
        shop_id = args["shop_id"]
        tenant.ensure_shop_access(shop_id)
        listings = self.warehouse.query_listings(tenant_id=tenant.tenant_id, shop_id=shop_id)
        ocr_lookup = {s.listing_id: s for s in self.warehouse.query_ocr()}
        data = run_product_pipeline(listings, ocr_lookup=ocr_lookup)
        stats = data.get("stats") or {}
        failed = int(stats.get("failed") or 0)
        return ToolResult(
            ok=True,
            name="run_product_pipeline",
            data=data,
            numeric_facts=[
                {
                    "metric_code": "pipeline_failed",
                    "value": float(failed),
                    "unit": "count",
                    "label": f"质检失败={failed}",
                }
            ],
            blocks=[
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code="pipeline_failed",
                    value=failed,
                    unit="count",
                    content=f"质检失败={failed}/{stats.get('total', 0)}",
                ),
                MessageBlock(
                    type=BlockType.TABLE.value,
                    columns=["listing_id", "ok", "category", "issues"],
                    rows=[
                        [
                            r["listing_id"],
                            r["validation"]["ok"],
                            (r["classified"] or {}).get("category"),
                            ",".join(i["code"] for i in r["validation"]["issues"]),
                        ]
                        for r in data.get("rows") or []
                    ],
                ),
            ],
        )

    def _detect_price_anomaly(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        self._ensure_analytics()
        shop_id = args["shop_id"]
        tenant.ensure_shop_access(shop_id)
        listings = self.warehouse.query_listings(tenant_id=tenant.tenant_id, shop_id=shop_id)
        data = detect_price_anomalies(listings)
        n = int(data.get("anomaly_count") or 0)
        anomalies = data.get("anomalies") or []
        return ToolResult(
            ok=True,
            name="detect_price_anomaly",
            data=data,
            numeric_facts=[
                {
                    "metric_code": "price_anomaly_count",
                    "value": float(n),
                    "unit": "count",
                    "label": f"价格异常={n}",
                }
            ],
            blocks=[
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code="price_anomaly_count",
                    value=n,
                    unit="count",
                    content=f"价格异常={n}",
                ),
                MessageBlock(
                    type=BlockType.TABLE.value,
                    columns=["listing_id", "category", "price", "median", "kind"],
                    rows=[
                        [
                            a.get("listing_id"),
                            a.get("category"),
                            a.get("price"),
                            a.get("median"),
                            a.get("kind"),
                        ]
                        for a in anomalies
                    ],
                ),
            ],
        )

    def _flag_invalid_orders(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        self._ensure_analytics()
        shop_id = args["shop_id"]
        tenant.ensure_shop_access(shop_id)
        rows = self.warehouse.query_orders(
            tenant_id=tenant.tenant_id,
            shop_id=shop_id,
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
        )
        data = flag_invalid_orders(rows)
        n = int(data.get("invalid_count") or 0)
        orders = data.get("orders") or []
        return ToolResult(
            ok=True,
            name="flag_invalid_orders",
            data=data,
            numeric_facts=[
                {
                    "metric_code": "invalid_order_count",
                    "value": float(n),
                    "unit": "count",
                    "label": f"无效订单={n}",
                }
            ],
            blocks=[
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code="invalid_order_count",
                    value=n,
                    unit="count",
                    content=f"无效订单={n}",
                ),
                MessageBlock(
                    type=BlockType.TABLE.value,
                    columns=["order_id", "status", "pay_amount", "reasons"],
                    rows=[
                        [
                            o.get("order_id"),
                            o.get("status"),
                            o.get("pay_amount"),
                            ",".join(o.get("reasons") or []),
                        ]
                        for o in orders
                    ],
                ),
            ],
        )

    def _forecast_sales(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        self._ensure_analytics()
        shop_id = args["shop_id"]
        tenant.ensure_shop_access(shop_id)
        horizon = int(args.get("horizon") or 7)
        series = self.warehouse.query_daily_sales(tenant_id=tenant.tenant_id, shop_id=shop_id, days=14)
        data = forecast_sales(series, horizon=horizon)
        baseline = float(data.get("baseline_gmv") or 0)
        fc = data.get("forecast") or []
        return ToolResult(
            ok=bool(data.get("ok", True)),
            name="forecast_sales",
            data=data,
            error_code=None if data.get("ok", True) else "FORECAST_INSUFFICIENT_HISTORY",
            error_message=data.get("error"),
            numeric_facts=[
                {
                    "metric_code": "forecast_baseline_gmv",
                    "value": baseline,
                    "unit": "CNY",
                    "label": f"预测基线GMV={baseline}",
                }
            ],
            blocks=[
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code="forecast_baseline_gmv",
                    value=baseline,
                    unit="CNY",
                    content=f"预测基线GMV={baseline}",
                ),
                MessageBlock(
                    type=BlockType.TABLE.value,
                    columns=["day", "gmv"],
                    rows=[[x.get("day"), x.get("gmv")] for x in fc],
                ),
            ],
        )

    def _run_workflow(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        self._ensure_analytics()
        shop_id = args["shop_id"]
        tenant.ensure_shop_access(shop_id)
        engine = WorkflowEngine(self.warehouse)
        result = engine.run(args["workflow"], tenant, shop_id)
        data = WorkflowEngine.to_dict(result)
        return ToolResult(
            ok=result.ok,
            name="run_workflow",
            data=data,
            blocks=[
                MessageBlock(
                    type=BlockType.TABLE.value,
                    columns=["step", "method", "ok", "ms"],
                    rows=[[s.name, s.method, s.ok, s.duration_ms] for s in result.steps],
                ),
                MessageBlock(type=BlockType.TEXT.value, content=result.note),
            ],
        )

    def _query_ad_performance(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        if not self.flags.ads_tool_enabled:
            raise ToolExecutionError("广告分析能力已降级关闭", code="TOOL_DISABLED")
        shop_id = args["shop_id"]
        tenant.ensure_shop_access(shop_id)
        rows = self.warehouse.query_ads(
            tenant_id=tenant.tenant_id,
            shop_id=shop_id,
            date_from=args.get("date_from"),
            date_to=args.get("date_to"),
        )
        data = summarize_ads(rows)
        return ToolResult(
            ok=True,
            name="query_ad_performance",
            data=data,
            numeric_facts=[
                {"metric_code": "ad_spend", "value": data["spend"], "unit": "CNY", "label": f"广告花费={data['spend']}"},
                {"metric_code": "ad_roi", "value": data["roi"], "unit": "ratio", "label": f"广告ROI={data['roi']}"},
            ],
            blocks=[
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code="ad_spend",
                    value=data["spend"],
                    unit="CNY",
                    content=f"广告花费={data['spend']}",
                ),
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code="ad_roi",
                    value=data["roi"],
                    unit="ratio",
                    content=f"广告ROI={data['roi']}",
                ),
                MessageBlock(
                    type=BlockType.TABLE.value,
                    columns=["campaign_id", "name", "spend", "gmv", "roi", "losing"],
                    rows=[
                        [c["campaign_id"], c["name"], c["spend"], c["gmv"], c["roi"], c["losing"]]
                        for c in data.get("campaigns") or []
                    ],
                ),
            ],
        )

    def _run_ocr_check(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        self._ensure_analytics()
        shop_id = args["shop_id"]
        tenant.ensure_shop_access(shop_id)
        listings = self.warehouse.query_listings(tenant_id=tenant.tenant_id, shop_id=shop_id)
        lookup = {s.listing_id: s for s in self.warehouse.query_ocr()}
        rows = []
        mismatch = 0
        for item in listings:
            ocr = fake_ocr(item, lookup.get(item.listing_id))
            bad = image_text_mismatch(item.title, ocr.ocr_text)
            if bad:
                mismatch += 1
            rows.append(
                {
                    "listing_id": item.listing_id,
                    "title": item.title,
                    "ocr_text": ocr.ocr_text,
                    "confidence": ocr.confidence,
                    "source": ocr.source,
                    "mismatch": bad,
                    "method": ocr.method,
                }
            )
        data = {
            "method": "fake_ocr",
            "note": "OCR 文本来自演示表，不是真实视觉模型",
            "total": len(rows),
            "mismatch_count": mismatch,
            "rows": rows,
        }
        return ToolResult(
            ok=True,
            name="run_ocr_check",
            data=data,
            numeric_facts=[
                {
                    "metric_code": "pipeline_failed",
                    "value": float(mismatch),
                    "unit": "count",
                    "label": f"图文不符={mismatch}",
                }
            ],
            blocks=[
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code="pipeline_failed",
                    value=mismatch,
                    unit="count",
                    content=f"图文不符={mismatch}/{len(rows)}",
                )
            ],
        )

    def _run_alert_scan(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        if not self.flags.alert_tool_enabled:
            raise ToolExecutionError("预警能力已降级关闭", code="TOOL_DISABLED")
        shop_id = args["shop_id"]
        tenant.ensure_shop_access(shop_id)
        events = scan_alerts(self.warehouse, tenant, shop_id)
        self.warehouse.replace_alerts(events, tenant_id=tenant.tenant_id, shop_id=shop_id)
        data = alerts_to_dict(events)
        open_n = int(data.get("open") or 0)
        return ToolResult(
            ok=True,
            name="run_alert_scan",
            data=data,
            numeric_facts=[
                {"metric_code": "alert_open_count", "value": float(open_n), "unit": "count", "label": f"未处理预警={open_n}"}
            ],
            blocks=[
                MessageBlock(
                    type=BlockType.METRIC.value,
                    metric_code="alert_open_count",
                    value=open_n,
                    unit="count",
                    content=f"未处理预警={open_n}",
                ),
                MessageBlock(
                    type=BlockType.TABLE.value,
                    columns=["id", "severity", "rule", "message", "status"],
                    rows=[[a["id"], a["severity"], a["rule"], a["message"], a["status"]] for a in data.get("alerts") or []],
                ),
            ],
        )

    def _list_alerts(self, tenant: TenantContext, args: dict[str, Any]) -> ToolResult:
        if not self.flags.alert_tool_enabled:
            raise ToolExecutionError("预警能力已降级关闭", code="TOOL_DISABLED")
        shop_id = args["shop_id"]
        tenant.ensure_shop_access(shop_id)
        status = args.get("status") or "open"
        events = self.warehouse.query_alerts(tenant_id=tenant.tenant_id, shop_id=shop_id)
        if status != "all":
            events = [e for e in events if e.status == status]
        data = alerts_to_dict(events)
        return ToolResult(ok=True, name="list_alerts", data=data)

