"""Sales forecast: moving-average baseline × toy weekday weights (not a trained net)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from emmerce_agent.application.ports import DailySale

# Mon..Sun multipliers — demo stand-in for a learned seasonal head
WEEKDAY_WEIGHTS = (0.92, 0.95, 1.0, 1.02, 1.08, 1.18, 1.12)


def forecast_sales(series: list[DailySale], *, horizon: int = 7, window: int = 7) -> dict[str, Any]:
    ordered = sorted(series, key=lambda x: x.day)
    values = [x.gmv for x in ordered]
    if len(values) < 3:
        return {
            "method": "toy_seasonal_weights",
            "ok": False,
            "error": "历史天数不足，无法做基线预测",
            "history": [],
            "forecast": [],
        }

    w = min(window, len(values))
    baseline = sum(values[-w:]) / w
    last_day = datetime.strptime(ordered[-1].day, "%Y-%m-%d")
    forecast = []
    for i in range(1, horizon + 1):
        day_dt = last_day + timedelta(days=i)
        day = day_dt.strftime("%Y-%m-%d")
        weight = WEEKDAY_WEIGHTS[day_dt.weekday()]
        forecast.append(
            {
                "day": day,
                "gmv": round(baseline * weight, 2),
                "weekday_weight": weight,
                "method": "toy_seasonal_weights",
            }
        )

    return {
        "method": "toy_seasonal_weights",
        "ok": True,
        "note": "窗口均值 × 演示星期权重，不是训练好的深度学习模型；可替换真实模型",
        "window": w,
        "baseline_gmv": round(baseline, 2),
        "weekday_weights": list(WEEKDAY_WEIGHTS),
        "history": [{"day": x.day, "gmv": x.gmv, "orders": x.order_count} for x in ordered],
        "forecast": forecast,
    }
