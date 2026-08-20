"""Named multi-step workflows. Same analytics functions as Agent tools (reusable)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from emmerce_agent.application.analytics.ads import summarize_ads
from emmerce_agent.application.analytics.alerts import alerts_to_dict, scan_alerts
from emmerce_agent.application.analytics.invalid_orders import flag_invalid_orders
from emmerce_agent.application.analytics.price_anomaly import detect_price_anomalies
from emmerce_agent.application.analytics.sales_forecast import forecast_sales
from emmerce_agent.application.data_pipeline.ocr import fake_ocr
from emmerce_agent.application.data_pipeline.run import run_product_pipeline
from emmerce_agent.application.data_pipeline.vision import image_text_mismatch
from emmerce_agent.application.ports import WarehousePort
from emmerce_agent.domain.tenancy import TenantContext


@dataclass
class WorkflowStepResult:
    name: str
    method: str
    ok: bool
    duration_ms: float
    summary: dict[str, Any]
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowResult:
    workflow: str
    shop_id: str
    ok: bool
    steps: list[WorkflowStepResult]
    note: str = ""


def _timed(name: str, method: str, fn: Callable[[], dict[str, Any]], *, ok_key: str | None = None) -> WorkflowStepResult:
    t0 = time.perf_counter()
    data = fn()
    ms = (time.perf_counter() - t0) * 1000
    ok = True if ok_key is None else bool(data.get(ok_key, True))
    summary = {k: data[k] for k in data if k not in {"rows", "orders", "anomalies", "history", "forecast", "baselines", "campaigns", "losing", "alerts"}}
    return WorkflowStepResult(name=name, method=method, ok=ok, duration_ms=round(ms, 2), summary=summary, data=data)


class WorkflowEngine:
    NAMES = ("product_qc", "ops_diagnosis", "ad_diagnosis")

    def __init__(self, warehouse: WarehousePort):
        self.warehouse = warehouse

    def run(self, name: str, tenant: TenantContext, shop_id: str) -> WorkflowResult:
        tenant.ensure_shop_access(shop_id)
        if name == "product_qc":
            return self._product_qc(tenant, shop_id)
        if name == "ops_diagnosis":
            return self._ops_diagnosis(tenant, shop_id)
        if name == "ad_diagnosis":
            return self._ad_diagnosis(tenant, shop_id)
        raise ValueError(f"未知工作流: {name}，可选 {self.NAMES}")

    def _product_qc(self, tenant: TenantContext, shop_id: str) -> WorkflowResult:
        listings = self.warehouse.query_listings(tenant_id=tenant.tenant_id, shop_id=shop_id)
        ocr_lookup = {s.listing_id: s for s in self.warehouse.query_ocr()}
        pipe = _timed(
            "extract_classify_validate",
            "rule_first+fake_ocr",
            lambda: run_product_pipeline(listings, ocr_lookup=ocr_lookup),
        )
        anomaly = _timed(
            "detect_price_anomaly",
            "stats_iqr",
            lambda: detect_price_anomalies(listings),
        )
        ok = pipe.ok and anomaly.ok
        return WorkflowResult(
            workflow="product_qc",
            shop_id=shop_id,
            ok=ok,
            steps=[pipe, anomaly],
            note="商品质检：假 OCR + 规则抽取/分类/校验 → 统计价格异常。",
        )

    def _ops_diagnosis(self, tenant: TenantContext, shop_id: str) -> WorkflowResult:
        orders = self.warehouse.query_orders(tenant_id=tenant.tenant_id, shop_id=shop_id)
        listings = self.warehouse.query_listings(tenant_id=tenant.tenant_id, shop_id=shop_id)
        daily = self.warehouse.query_daily_sales(tenant_id=tenant.tenant_id, shop_id=shop_id, days=14)
        gmv = round(sum(r.pay_amount for r in orders), 2)
        gmv_step = WorkflowStepResult(
            name="query_gmv",
            method="sql_agg",
            ok=True,
            duration_ms=0.0,
            summary={"gmv_pay": gmv, "order_rows": len(orders)},
            data={"gmv_pay": gmv},
        )
        invalid = _timed("flag_invalid_orders", "rule", lambda: flag_invalid_orders(orders))
        anomaly = _timed("detect_price_anomaly", "stats_iqr", lambda: detect_price_anomalies(listings))
        fc = _timed("forecast_sales", "toy_seasonal_weights", lambda: forecast_sales(daily), ok_key="ok")
        ads = _timed(
            "query_ad_performance",
            "rule_agg",
            lambda: summarize_ads(self.warehouse.query_ads(tenant_id=tenant.tenant_id, shop_id=shop_id)),
        )
        return WorkflowResult(
            workflow="ops_diagnosis",
            shop_id=shop_id,
            ok=all(s.ok for s in (gmv_step, invalid, anomaly, fc, ads)),
            steps=[gmv_step, invalid, anomaly, fc, ads],
            note="经营诊断：GMV → 无效单 → 价格异常 → 星期权重预测 → 演示广告 ROI。",
        )

    def _ad_diagnosis(self, tenant: TenantContext, shop_id: str) -> WorkflowResult:
        ads = _timed(
            "query_ad_performance",
            "rule_agg",
            lambda: summarize_ads(self.warehouse.query_ads(tenant_id=tenant.tenant_id, shop_id=shop_id)),
        )

        def _ocr() -> dict[str, Any]:
            listings = self.warehouse.query_listings(tenant_id=tenant.tenant_id, shop_id=shop_id)
            lookup = {s.listing_id: s for s in self.warehouse.query_ocr()}
            mismatch = 0
            for item in listings:
                if image_text_mismatch(item.title, fake_ocr(item, lookup.get(item.listing_id)).ocr_text):
                    mismatch += 1
            return {"method": "fake_ocr", "total": len(listings), "mismatch_count": mismatch}

        ocr = _timed("run_ocr_check", "fake_ocr", _ocr)

        def _scan() -> dict[str, Any]:
            events = scan_alerts(self.warehouse, tenant, shop_id)
            self.warehouse.replace_alerts(events, tenant_id=tenant.tenant_id, shop_id=shop_id)
            return alerts_to_dict(events)

        alerts = _timed("run_alert_scan", "rule_threshold", _scan)
        return WorkflowResult(
            workflow="ad_diagnosis",
            shop_id=shop_id,
            ok=ads.ok and ocr.ok and alerts.ok,
            steps=[ads, ocr, alerts],
            note="投放诊断：广告聚合 → 假 OCR 图文 → 阈值预警（演示数据）。",
        )

    @staticmethod
    def to_dict(result: WorkflowResult) -> dict[str, Any]:
        return {
            "workflow": result.workflow,
            "shop_id": result.shop_id,
            "ok": result.ok,
            "note": result.note,
            "steps": [
                {
                    "name": s.name,
                    "method": s.method,
                    "ok": s.ok,
                    "duration_ms": s.duration_ms,
                    "summary": s.summary,
                }
                for s in result.steps
            ],
            "details": {s.name: s.data for s in result.steps},
        }
