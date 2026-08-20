"""Deterministic metric formulas over warehouse order rows."""

from __future__ import annotations

from emmerce_agent.application.ports import WarehouseRow
from emmerce_agent.domain.errors import ToolExecutionError


def paid_orders(rows: list[WarehouseRow]) -> list[WarehouseRow]:
    return [r for r in rows if r.status == "paid" and r.pay_amount > 0]


def compute_metric(metric_code: str, rows: list[WarehouseRow]) -> tuple[float, str]:
    if metric_code == "gmv_pay":
        return round(sum(r.pay_amount for r in rows), 2), "sum(pay_amount)"
    if metric_code == "order_count":
        return float(len(paid_orders(rows))), "count(status=paid and pay_amount>0)"
    if metric_code == "aov":
        paid = paid_orders(rows)
        gmv = sum(r.pay_amount for r in paid)
        cnt = len(paid)
        return (0.0 if cnt == 0 else round(gmv / cnt, 2)), "gmv_pay / paid_order_count"
    if metric_code == "refund_rate":
        paid_n = len(paid_orders(rows))
        refund_n = sum(1 for r in rows if r.status == "refunded")
        denom = paid_n + refund_n
        value = 0.0 if denom == 0 else round(refund_n / denom, 4)
        return value, "refunded / (paid_positive + refunded)"
    if metric_code == "sell_through_rate":
        sold = sum(r.sold_qty for r in rows)
        stock = sum(r.stock_qty for r in rows)
        denom = sold + stock
        return (0.0 if denom <= 0 else round(sold / denom, 4)), "sold_qty / (sold_qty + stock_qty)"
    if metric_code == "slow_moving_count":
        return float(sum(1 for r in rows if r.stock_qty >= 50 and r.sold_qty <= 5)), "count(slow_moving_sku)"
    raise ToolExecutionError(f"工具暂不支持计算 {metric_code}", code="UNSUPPORTED_METRIC")
