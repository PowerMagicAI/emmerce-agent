"""Price anomaly: category IQR / median — stats first, LLM only explains."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from emmerce_agent.application.ports import ProductListing


def _median(xs: list[float]) -> float:
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    if n % 2:
        return ys[mid]
    return (ys[mid - 1] + ys[mid]) / 2


def _percentile(xs: list[float], p: float) -> float:
    ys = sorted(xs)
    if not ys:
        return 0.0
    k = (len(ys) - 1) * p
    f = int(k)
    c = min(f + 1, len(ys) - 1)
    if f == c:
        return ys[f]
    return ys[f] + (ys[c] - ys[f]) * (k - f)


def detect_price_anomalies(listings: list[ProductListing]) -> dict[str, Any]:
    by_cat: dict[str, list[tuple[ProductListing, float]]] = defaultdict(list)
    skipped = 0
    for item in listings:
        if item.listed_price is None or item.listed_price <= 0:
            skipped += 1
            continue
        cat = item.listed_category or "未知"
        by_cat[cat].append((item, float(item.listed_price)))

    anomalies: list[dict[str, Any]] = []
    baselines: list[dict[str, Any]] = []
    for cat, pairs in by_cat.items():
        prices = [p for _, p in pairs]
        if len(prices) < 3:
            continue
        q1 = _percentile(prices, 0.25)
        q3 = _percentile(prices, 0.75)
        iqr = max(q3 - q1, 1e-6)
        med = _median(prices)
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        baselines.append(
            {
                "category": cat,
                "n": len(prices),
                "median": round(med, 2),
                "q1": round(q1, 2),
                "q3": round(q3, 2),
                "fence": [round(low, 2), round(high, 2)],
            }
        )
        for item, price in pairs:
            if price < low or price > high or price < 0.2 * med or price > 8 * med:
                kind = "过低" if price < med else "过高"
                anomalies.append(
                    {
                        "listing_id": item.listing_id,
                        "sku": item.sku,
                        "title": item.title,
                        "category": cat,
                        "price": price,
                        "median": round(med, 2),
                        "kind": kind,
                        "method": "stats_iqr",
                    }
                )

    return {
        "method": "stats_iqr",
        "note": "异常由分位数/IQR 判定；LLM 只负责解释，不改写数字",
        "skipped_no_price": skipped,
        "anomaly_count": len(anomalies),
        "baselines": baselines,
        "anomalies": anomalies,
    }
