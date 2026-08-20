"""Demo advertising metrics over campaign rows. Not a live ad platform."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from emmerce_agent.application.ports import AdRow


def summarize_ads(rows: list[AdRow]) -> dict[str, Any]:
    spend = round(sum(r.spend for r in rows), 2)
    gmv = round(sum(r.gmv for r in rows), 2)
    clicks = int(sum(r.clicks for r in rows))
    orders = int(sum(r.orders for r in rows))
    roi = 0.0 if spend <= 0 else round(gmv / spend, 4)
    by_campaign: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"spend": 0.0, "gmv": 0.0, "clicks": 0, "orders": 0, "name": "", "channel": ""}
    )
    for r in rows:
        b = by_campaign[r.campaign_id]
        b["name"] = r.name
        b["channel"] = r.channel
        b["spend"] = round(b["spend"] + r.spend, 2)
        b["gmv"] = round(b["gmv"] + r.gmv, 2)
        b["clicks"] += r.clicks
        b["orders"] += r.orders
    campaigns = []
    for cid, b in sorted(by_campaign.items()):
        c_roi = 0.0 if b["spend"] <= 0 else round(b["gmv"] / b["spend"], 4)
        campaigns.append(
            {
                "campaign_id": cid,
                "name": b["name"],
                "channel": b["channel"],
                "spend": b["spend"],
                "gmv": b["gmv"],
                "clicks": b["clicks"],
                "orders": b["orders"],
                "roi": c_roi,
                "losing": c_roi < 1.0 and b["spend"] > 0,
            }
        )
    losing = [c for c in campaigns if c["losing"]]
    return {
        "method": "rule_agg",
        "note": "演示投放流水，不是广告平台实时拉取",
        "spend": spend,
        "gmv": gmv,
        "clicks": clicks,
        "orders": orders,
        "roi": roi,
        "campaign_count": len(campaigns),
        "losing_count": len(losing),
        "campaigns": campaigns,
        "losing": losing,
    }
