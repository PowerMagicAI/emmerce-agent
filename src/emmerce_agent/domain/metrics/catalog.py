"""Metric catalog — single source of truth for口径."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    metric_code: str
    name: str
    aliases: tuple[str, ...]
    formula: str
    grain: str
    latency: str
    channels: tuple[str, ...]
    common_misuse: str
    version: str
    unit: str = "CNY"


@dataclass
class MetricCatalog:
    """In-process registry; production may load from DB/CMS with same interface."""

    _by_code: dict[str, MetricDefinition] = field(default_factory=dict)
    _alias_index: dict[str, str] = field(default_factory=dict)

    def register(self, metric: MetricDefinition) -> None:
        self._by_code[metric.metric_code] = metric
        for alias in (metric.name, *metric.aliases, metric.metric_code):
            self._alias_index[alias.strip().lower()] = metric.metric_code

    def get(self, code: str) -> MetricDefinition | None:
        return self._by_code.get(code)

    def require(self, code: str) -> MetricDefinition:
        m = self.get(code)
        if not m:
            raise KeyError(f"未知指标: {code}")
        return m

    def resolve_alias(self, text: str) -> MetricDefinition | None:
        code = self._alias_index.get(text.strip().lower())
        return self.get(code) if code else None

    def list_all(self) -> list[MetricDefinition]:
        return list(self._by_code.values())

    def allowed_codes(self) -> set[str]:
        return set(self._by_code.keys())


def build_default_catalog() -> MetricCatalog:
    catalog = MetricCatalog()
    catalog.register(
        MetricDefinition(
            metric_code="gmv_pay",
            name="支付GMV",
            aliases=("成交额", "支付 GMV", "GMV", "支付金额", "今日销售额", "营业额"),
            formula="sum(pay_amount)",
            grain="店铺/日",
            latency="T+0或T+1按环境",
            channels=("taobao", "douyin", "channels"),
            common_misuse="把下单GMV当成支付GMV",
            version="1.0",
            unit="CNY",
        )
    )
    catalog.register(
        MetricDefinition(
            metric_code="aov",
            name="客单价",
            aliases=("件单价", "AOV", "平均客单"),
            formula="gmv_pay / order_count",
            grain="店铺/日",
            latency="同GMV",
            channels=("taobao", "douyin", "channels"),
            common_misuse="用访客数做分母",
            version="1.0",
            unit="CNY",
        )
    )
    catalog.register(
        MetricDefinition(
            metric_code="order_count",
            name="有效订单量",
            aliases=("订单量", "订单数", "成交单数", "支付订单数"),
            formula="count(status=paid and pay_amount>0)",
            grain="店铺/日",
            latency="同GMV",
            channels=("taobao", "douyin", "channels"),
            common_misuse="把取消单和0元单算进成交",
            version="1.0",
            unit="count",
        )
    )
    catalog.register(
        MetricDefinition(
            metric_code="refund_rate",
            name="退款率",
            aliases=("退款比例", "退货率"),
            formula="refunded / (paid_positive + refunded)",
            grain="店铺/日",
            latency="同GMV",
            channels=("taobao", "douyin", "channels"),
            common_misuse="用GMV金额当退款率分母",
            version="1.0",
            unit="ratio",
        )
    )
    catalog.register(
        MetricDefinition(
            metric_code="slow_moving_count",
            name="滞销商品数",
            aliases=("滞销", "滞销SKU", "不动销", "卖不动的货"),
            formula="count(sku where stock_qty>=50 and sold_qty<=5)",
            grain="店铺/月",
            latency="库存快照",
            channels=("taobao", "douyin", "channels"),
            common_misuse="忽略在途库存",
            version="1.0",
            unit="count",
        )
    )
    catalog.register(
        MetricDefinition(
            metric_code="sell_through_rate",
            name="售罄率",
            aliases=("动销率",),
            formula="sold_qty / (sold_qty + stock_qty)",
            grain="SKU/周期",
            latency="库存快照",
            channels=("taobao", "douyin", "channels"),
            common_misuse="忽略在途库存",
            version="1.0",
            unit="ratio",
        )
    )
    catalog.register(
        MetricDefinition(
            metric_code="ad_spend",
            name="广告花费",
            aliases=("投放花费", "推广花费", "广告消耗"),
            formula="sum(ad.spend)",
            grain="店铺/日",
            latency="T+0演示",
            channels=("taobao",),
            common_misuse="把广告花费加进支付GMV",
            version="1.0",
            unit="CNY",
        )
    )
    catalog.register(
        MetricDefinition(
            metric_code="ad_roi",
            name="广告ROI",
            aliases=("投放ROI", "投产比", "广告回报"),
            formula="ad_gmv / ad_spend",
            grain="店铺/日",
            latency="T+0演示",
            channels=("taobao",),
            common_misuse="用心算ROI替代工具结果",
            version="1.0",
            unit="ratio",
        )
    )
    return catalog
