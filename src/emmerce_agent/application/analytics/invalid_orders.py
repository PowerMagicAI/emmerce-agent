"""Invalid / dirty orders: deterministic rules. Grey cases can be sent to LLM later."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from emmerce_agent.application.ports import WarehouseRow

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def flag_invalid_orders(rows: list[WarehouseRow]) -> dict[str, Any]:
    id_counts = Counter(r.order_id for r in rows if r.order_id)
    flagged: list[dict[str, Any]] = []

    for r in rows:
        reasons: list[str] = []
        if r.status in {"cancelled", "refunded"}:
            reasons.append(f"status={r.status}")
        if r.pay_amount < 0:
            reasons.append("negative_amount")
        if r.status == "paid" and r.pay_amount == 0:
            reasons.append("zero_pay_paid")
        if r.order_id and id_counts[r.order_id] > 1:
            reasons.append("duplicate_order_id")
        if r.phone and not PHONE_RE.match(r.phone):
            reasons.append("invalid_phone")
        if r.sold_qty < 0 or r.stock_qty < 0:
            reasons.append("negative_qty")
        if not reasons:
            continue
        flagged.append(
            {
                "order_id": r.order_id or r.sku,
                "sku": r.sku,
                "status": r.status,
                "pay_amount": r.pay_amount,
                "reasons": reasons,
                "method": "rule",
            }
        )

    return {
        "method": "rule",
        "note": "硬特征走规则；灰色样本（如异常收货地址语义）才交 LLM",
        "scanned": len(rows),
        "invalid_count": len(flagged),
        "orders": flagged,
    }
