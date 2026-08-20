"""Threshold alerts over demo warehouse facts. No push channel."""

from __future__ import annotations

from typing import Any

from emmerce_agent.application.analytics.ads import summarize_ads
from emmerce_agent.application.analytics.metrics import compute_metric
from emmerce_agent.application.data_pipeline.ocr import fake_ocr
from emmerce_agent.application.data_pipeline.vision import image_text_mismatch
from emmerce_agent.application.ports import AlertEvent, OcrSample, WarehousePort
from emmerce_agent.domain.context import utcnow
from emmerce_agent.domain.tenancy import TenantContext


def scan_alerts(
    warehouse: WarehousePort,
    tenant: TenantContext,
    shop_id: str,
    *,
    ocr_lookup: dict[str, OcrSample] | None = None,
) -> list[AlertEvent]:
    tenant.ensure_shop_access(shop_id)
    now = utcnow().isoformat()
    events: list[AlertEvent] = []
    orders = warehouse.query_orders(tenant_id=tenant.tenant_id, shop_id=shop_id)
    ads = warehouse.query_ads(tenant_id=tenant.tenant_id, shop_id=shop_id)
    listings = warehouse.query_listings(tenant_id=tenant.tenant_id, shop_id=shop_id)
    lookup = ocr_lookup or {s.listing_id: s for s in warehouse.query_ocr()}

    refund, _ = compute_metric("refund_rate", orders)
    if refund >= 0.2:
        events.append(
            AlertEvent(
                id=f"al_refund_{shop_id}",
                tenant_id=tenant.tenant_id,
                shop_id=shop_id,
                severity="medium",
                rule="refund_rate_high",
                message=f"退款率 {refund}，超过阈值 0.2",
                metric_code="refund_rate",
                value=refund,
                status="open",
                created_at=now,
            )
        )

    summary = summarize_ads(ads)
    for camp in summary.get("losing") or []:
        events.append(
            AlertEvent(
                id=f"al_ad_{shop_id}_{camp['campaign_id']}",
                tenant_id=tenant.tenant_id,
                shop_id=shop_id,
                severity="high",
                rule="ad_roi_low",
                message=f"投放计划 {camp['campaign_id']} {camp['name']} ROI={camp['roi']}，低于 1.0",
                metric_code="ad_roi",
                value=float(camp["roi"]),
                status="open",
                created_at=now,
            )
        )

    mismatch = 0
    for item in listings:
        ocr = fake_ocr(item, lookup.get(item.listing_id))
        if image_text_mismatch(item.title, ocr.ocr_text):
            mismatch += 1
    if mismatch:
        events.append(
            AlertEvent(
                id=f"al_ocr_{shop_id}",
                tenant_id=tenant.tenant_id,
                shop_id=shop_id,
                severity="medium",
                rule="image_text_mismatch",
                message=f"{mismatch} 条商品主图假 OCR 与标题不一致",
                metric_code="pipeline_failed",
                value=float(mismatch),
                status="open",
                created_at=now,
            )
        )
    return events


def alerts_to_dict(events: list[AlertEvent]) -> dict[str, Any]:
    open_n = sum(1 for e in events if e.status == "open")
    return {
        "method": "rule_threshold",
        "note": "演示预警：阈值扫描，无真实推送",
        "total": len(events),
        "open": open_n,
        "alerts": [
            {
                "id": e.id,
                "shop_id": e.shop_id,
                "severity": e.severity,
                "rule": e.rule,
                "message": e.message,
                "metric_code": e.metric_code,
                "value": e.value,
                "status": e.status,
                "created_at": e.created_at,
            }
            for e in events
        ],
    }
