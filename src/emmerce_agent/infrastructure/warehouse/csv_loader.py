"""Load reproducible CSV demo datasets."""

from __future__ import annotations

import csv
from pathlib import Path

from emmerce_agent.application.ports import AdRow, AlertEvent, DailySale, OcrSample, ProductListing, WarehouseRow
from emmerce_agent.infrastructure.warehouse.memory_warehouse import MemoryWarehouse


def default_dataset_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "datasets" / "demo"


def _f(v: str) -> float | None:
    v = (v or "").strip()
    if v == "":
        return None
    return float(v)


def load_demo_csv(wh: MemoryWarehouse, data_dir: Path | None = None) -> Path:
    root = Path(data_dir) if data_dir else default_dataset_dir()
    orders_path = root / "orders.csv"
    listings_path = root / "listings.csv"
    daily_path = root / "daily_sales.csv"
    if not orders_path.is_file():
        raise FileNotFoundError(f"demo dataset missing: {orders_path}")

    rows: list[WarehouseRow] = []
    with orders_path.open(encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            rows.append(
                WarehouseRow(
                    tenant_id=rec["tenant_id"],
                    shop_id=rec["shop_id"],
                    pay_amount=float(rec["pay_amount"] or 0),
                    sku=rec.get("sku") or "",
                    sold_qty=float(rec.get("sold_qty") or 0),
                    stock_qty=float(rec.get("stock_qty") or 0),
                    phone=rec.get("phone") or "",
                    buyer_name=rec.get("buyer_name") or "",
                    order_id=rec.get("order_id") or "",
                    status=rec.get("status") or "paid",
                    paid_at=rec.get("paid_at") or None,
                    unit_price=float(rec.get("unit_price") or 0),
                    category=rec.get("category") or "",
                    title=rec.get("title") or "",
                )
            )
    wh.seed(rows)

    listings: list[ProductListing] = []
    with listings_path.open(encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            listings.append(
                ProductListing(
                    tenant_id=rec["tenant_id"],
                    shop_id=rec["shop_id"],
                    listing_id=rec["listing_id"],
                    title=rec.get("title") or "",
                    listed_price=_f(rec.get("listed_price") or ""),
                    listed_category=rec.get("listed_category") or "",
                    sku=rec.get("sku") or "",
                    image_text=rec.get("image_text") or "",
                )
            )
    wh.listings = listings

    daily: list[DailySale] = []
    with daily_path.open(encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            daily.append(
                DailySale(
                    tenant_id=rec["tenant_id"],
                    shop_id=rec["shop_id"],
                    day=rec["day"],
                    gmv=float(rec["gmv"]),
                    order_count=int(rec["order_count"]),
                )
            )
    wh.daily = daily

    ads_path = root / "ads.csv"
    if ads_path.is_file():
        ads: list[AdRow] = []
        with ads_path.open(encoding="utf-8") as f:
            for rec in csv.DictReader(f):
                ads.append(
                    AdRow(
                        tenant_id=rec["tenant_id"],
                        shop_id=rec["shop_id"],
                        campaign_id=rec["campaign_id"],
                        name=rec.get("name") or rec["campaign_id"],
                        channel=rec.get("channel") or "taobao",
                        day=rec["day"],
                        spend=float(rec.get("spend") or 0),
                        clicks=int(float(rec.get("clicks") or 0)),
                        orders=int(float(rec.get("orders") or 0)),
                        gmv=float(rec.get("gmv") or 0),
                    )
                )
        wh.ads = ads

    ocr_path = root / "ocr.csv"
    if ocr_path.is_file():
        ocr: list[OcrSample] = []
        with ocr_path.open(encoding="utf-8") as f:
            for rec in csv.DictReader(f):
                ocr.append(
                    OcrSample(
                        listing_id=rec["listing_id"],
                        ocr_text=rec.get("ocr_text") or "",
                        confidence=float(rec.get("confidence") or 0),
                    )
                )
        wh.ocr = ocr

    alerts_path = root / "alerts.csv"
    if alerts_path.is_file():
        alerts: list[AlertEvent] = []
        with alerts_path.open(encoding="utf-8") as f:
            for rec in csv.DictReader(f):
                alerts.append(
                    AlertEvent(
                        id=rec["alert_id"],
                        tenant_id=rec["tenant_id"],
                        shop_id=rec["shop_id"],
                        severity=rec.get("severity") or "medium",
                        rule=rec.get("rule") or "",
                        message=rec.get("message") or "",
                        metric_code=rec.get("metric_code") or "",
                        value=float(rec.get("value") or 0),
                        status=rec.get("status") or "open",
                        created_at=rec.get("created_at") or "",
                    )
                )
        wh.alerts = alerts
    return root
