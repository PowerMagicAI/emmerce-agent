"""In-memory warehouse adapter (swap for MySQL/MaxCompute in production)."""

from __future__ import annotations

from datetime import datetime, timedelta

from emmerce_agent.application.ports import AdRow, AlertEvent, DailySale, OcrSample, ProductListing, WarehousePort, WarehouseRow
from emmerce_agent.domain.errors import ToolExecutionError


def _in_range(day: str | None, date_from: str | None, date_to: str | None) -> bool:
    if not day:
        return True
    if date_from and day < date_from:
        return False
    if date_to and day > date_to:
        return False
    return True


class MemoryWarehouse(WarehousePort):
    def __init__(self) -> None:
        self.rows: list[WarehouseRow] = []
        self.listings: list[ProductListing] = []
        self.daily: list[DailySale] = []
        self.ads: list[AdRow] = []
        self.ocr: list[OcrSample] = []
        self.alerts: list[AlertEvent] = []
        self._fail_budget = 0
        self.latency_ms = 0.0

    def seed(self, rows: list[WarehouseRow]) -> None:
        self.rows = list(rows)

    def set_transient_failures(self, n: int) -> None:
        self._fail_budget = n

    def query_orders(
        self,
        *,
        tenant_id: str,
        shop_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[WarehouseRow]:
        if self._fail_budget > 0:
            self._fail_budget -= 1
            raise ToolExecutionError(
                "SELECT * FROM orders WHERE ... timeout",
                code="WAREHOUSE_TIMEOUT",
                retryable=True,
            )
        out = [r for r in self.rows if r.tenant_id == tenant_id and r.shop_id == shop_id]
        if date_from or date_to:
            out = [r for r in out if _in_range(r.paid_at, date_from, date_to)]
        return out

    def query_listings(self, *, tenant_id: str, shop_id: str) -> list[ProductListing]:
        return [x for x in self.listings if x.tenant_id == tenant_id and x.shop_id == shop_id]

    def query_daily_sales(self, *, tenant_id: str, shop_id: str, days: int = 14) -> list[DailySale]:
        rows = [d for d in self.daily if d.tenant_id == tenant_id and d.shop_id == shop_id]
        rows.sort(key=lambda x: x.day)
        return rows[-days:]

    def query_ads(
        self,
        *,
        tenant_id: str,
        shop_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[AdRow]:
        out = [r for r in self.ads if r.tenant_id == tenant_id and r.shop_id == shop_id]
        if date_from or date_to:
            out = [r for r in out if _in_range(r.day, date_from, date_to)]
        return out

    def query_ocr(self) -> list[OcrSample]:
        return list(self.ocr)

    def query_alerts(self, *, tenant_id: str, shop_id: str | None = None) -> list[AlertEvent]:
        rows = [a for a in self.alerts if a.tenant_id == tenant_id]
        if shop_id:
            rows = [a for a in rows if a.shop_id == shop_id]
        return rows

    def replace_alerts(self, events: list[AlertEvent], *, tenant_id: str, shop_id: str) -> None:
        kept = [a for a in self.alerts if not (a.tenant_id == tenant_id and a.shop_id == shop_id)]
        self.alerts = kept + list(events)

    def ack_alert(self, alert_id: str, *, tenant_id: str) -> AlertEvent | None:
        for a in self.alerts:
            if a.id == alert_id and a.tenant_id == tenant_id:
                a.status = "acked"
                return a
        return None


def seed_demo_warehouse(wh: MemoryWarehouse) -> None:
    """Keep shop_a1 GMV = 3800.5 (existing tests). Extra dirty rows use pay_amount=0."""
    wh.seed(
        [
            WarehouseRow(
                "tenant_a", "shop_a1", 1000.0, "SKU-1", 2, 80, "13812345678", "张三",
                order_id="O-1001", status="paid", paid_at="2026-08-04", unit_price=500, category="数码",
                title="【索尼】耳机",
            ),
            WarehouseRow(
                "tenant_a", "shop_a1", 2500.5, "SKU-2", 1, 60, "13900001111", "李四",
                order_id="O-1002", status="paid", paid_at="2026-08-04", unit_price=2500.5, category="数码",
                title="【华为】平板",
            ),
            WarehouseRow(
                "tenant_a", "shop_a1", 300.0, "SKU-3", 40, 10, "", "",
                order_id="O-1003", status="paid", paid_at="2026-08-03", unit_price=7.5, category="食品",
                title="每日坚果",
            ),
            WarehouseRow("tenant_a", "shop_a2", 9999.0, "SKU-X", 0, 100, "", "", order_id="O-2001"),
            WarehouseRow("tenant_b", "shop_b1", 88888.0, "SKU-B", 0, 200, "13700000000", "", order_id="O-9001"),
            # Invalid / dirty — pay_amount=0 so GMV stays 3800.5
            WarehouseRow(
                "tenant_a", "shop_a1", 0.0, "SKU-4", 0, 0, "12345", "异常买家",
                order_id="O-BAD1", status="cancelled", paid_at="2026-08-04",
            ),
            WarehouseRow(
                "tenant_a", "shop_a1", 0.0, "SKU-5", 0, 0, "13800001111", "退款用户",
                order_id="O-BAD2", status="refunded", paid_at="2026-08-02",
            ),
            WarehouseRow(
                "tenant_a", "shop_a1", 0.0, "SKU-6", 0, 0, "13800002222", "重复单",
                order_id="O-DUP", status="paid", paid_at="2026-08-01",
            ),
            WarehouseRow(
                "tenant_a", "shop_a1", 0.0, "SKU-6b", 0, 0, "13800002222", "重复单",
                order_id="O-DUP", status="paid", paid_at="2026-08-01",
            ),
        ]
    )
    wh.listings = [
        ProductListing("tenant_a", "shop_a1", "L1", "【索尼】降噪耳机 500g", 199.0, "数码", "SKU-E1"),
        ProductListing("tenant_a", "shop_a1", "L2", "【华为】无线充电器", 89.0, "数码", "SKU-E2"),
        ProductListing("tenant_a", "shop_a1", "L3", "蓝牙键盘办公套装", 129.0, "数码", "SKU-E3"),
        ProductListing("tenant_a", "shop_a1", "L4", "【苹果】手机 价格99999", 99999.0, "数码", "SKU-E4"),
        ProductListing("tenant_a", "shop_a1", "L5", "【平价】耳机 ￥9.9", 9.9, "数码", "SKU-E5"),
        ProductListing("tenant_a", "shop_a1", "L6", "补水保湿面膜 25ml", 39.9, "美妆", "SKU-M1"),
        ProductListing("tenant_a", "shop_a1", "L7", "口红唇釉套装", 79.0, "美妆", "SKU-M2"),
        ProductListing("tenant_a", "shop_a1", "L8", "防晒喷雾", 59.0, "美妆", "SKU-M3"),
        ProductListing("tenant_a", "shop_a1", "L9", "连衣裙夏季新款", 128.0, "女装", "SKU-C1"),
        ProductListing("tenant_a", "shop_a1", "L10", "【错挂】面膜精华液", 49.0, "数码", "SKU-BADCAT"),
        ProductListing("tenant_a", "shop_a1", "L11", "", None, "美妆", "SKU-EMPTY"),
        ProductListing("tenant_a", "shop_a1", "L12", "神秘商品XYZ", None, "", "SKU-AMBIG"),
        ProductListing("tenant_a", "shop_a1", "L13", "高仿苹果手机 全新", 899.0, "数码", "SKU-FAKE", "手机外观"),
        ProductListing("tenant_a", "shop_a1", "L14", "【索尼】降噪耳机", 199.0, "数码", "SKU-MISMATCH", "儿童益智积木玩具实拍"),
        ProductListing("tenant_a", "shop_a2", "L20", "【索尼】耳机", 188.0, "数码", "SKU-X1"),
    ]
    start = datetime(2026, 7, 22)
    daily: list[DailySale] = []
    base = 240.0
    for i in range(14):
        day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        gmv = round(base + (i % 5) * 35 + (20 if i >= 10 else 0), 2)
        daily.append(DailySale("tenant_a", "shop_a1", day, gmv, 3 + i % 4))
    wh.daily = daily
    wh.ads = [
        AdRow("tenant_a", "shop_a1", "AD1", "耳机搜索", "taobao", "2026-08-03", 400, 90, 3, 900),
        AdRow("tenant_a", "shop_a1", "AD2", "品牌曝光", "taobao", "2026-08-03", 1000, 40, 1, 200),
        AdRow("tenant_a", "shop_a1", "AD1", "耳机搜索", "taobao", "2026-08-04", 800, 120, 4, 1600),
        AdRow("tenant_a", "shop_a1", "AD2", "品牌曝光", "taobao", "2026-08-04", 2000, 80, 1, 400),
        AdRow("tenant_a", "shop_a1", "AD3", "新品点击", "taobao", "2026-08-04", 200, 50, 2, 500),
    ]
    wh.ocr = [OcrSample("L14", "儿童益智积木玩具实拍", 0.95)]
    wh.alerts = []
