"""JD-aligned analytics: pipeline, stats/rules tools, workflows, eval routing."""

from __future__ import annotations

import json
from pathlib import Path

from emmerce_agent.application.ports import LLMMessage
from emmerce_agent.application.workflow.engine import WorkflowEngine
from emmerce_agent.domain.tenancy import TenantContext
from emmerce_agent.infrastructure.composition import build_container
from emmerce_agent.infrastructure.llm.stub import StubLLMAdapter


def _tenant() -> TenantContext:
    return TenantContext("tenant_a", "user_a_owner", ("shop_a1", "shop_a2"), ("owner",), True)


def test_date_filter_on_orders():
    c = build_container()
    all_rows = c.gateway.warehouse.query_orders(tenant_id="tenant_a", shop_id="shop_a1")
    day = c.gateway.warehouse.query_orders(
        tenant_id="tenant_a", shop_id="shop_a1", date_from="2026-08-04", date_to="2026-08-04"
    )
    assert len(day) < len(all_rows)
    assert round(sum(r.pay_amount for r in day), 2) == 3500.5

    c = build_container()
    tenant = _tenant()
    ses = c.agent.create_session(tenant, shop_id="shop_a1")
    resp = c.agent.chat(ses.session_id, "今日支付GMV是多少", shop_id="shop_a1")
    metric = next(b for b in resp.blocks if b.type == "metric")
    assert metric.value == 3800.5


def test_product_pipeline_flags_dirty_listings():
    c = build_container()
    out = c.gateway.execute(_tenant(), "run_product_pipeline", {"shop_id": "shop_a1"}).data
    stats = out["stats"]
    assert stats["total"] >= 10
    assert stats["failed"] >= 2
    assert stats["needs_llm"] >= 1
    failed = {r["listing_id"]: r for r in out["rows"] if not r["validation"]["ok"]}
    assert "L11" in failed
    assert any(i["code"] == "BANNED_WORD" for i in failed["L13"]["validation"]["issues"])
    assert any(i["code"] == "IMAGE_TEXT_MISMATCH" for i in failed["L14"]["validation"]["issues"])


def test_extract_slots_color_size_material():
    from emmerce_agent.application.data_pipeline.extract import extract_listing

    ex = extract_listing(listing_id="x", title="连衣裙夏季新款 M码 棉 黑色")
    assert ex.size == "M码"
    assert ex.color == "黑色"
    assert ex.material == "棉"
    banned = extract_listing(listing_id="y", title="高仿苹果手机")
    assert "高仿" in banned.banned


def test_ops_snapshot_after_tool():
    c = build_container()
    c.gateway.execute(_tenant(), "query_metric", {"shop_id": "shop_a1", "metric_code": "gmv_pay"})
    snap = c.ops.snapshot()
    assert snap["tool_calls"] >= 1
    assert snap["tool_ok"] >= 1
    assert snap["by_tool"]["query_metric"]["ok"] >= 1


def test_chat_emits_tool_events():
    c = build_container()
    tenant = _tenant()
    ses = c.agent.create_session(tenant, shop_id="shop_a1")
    events: list[tuple[str, dict]] = []
    c.agent.chat(
        ses.session_id,
        "今日支付GMV是多少",
        shop_id="shop_a1",
        on_event=lambda k, d: events.append((k, d)),
    )
    assert any(k == "tool" for k, _ in events)
    assert any(d.get("tool") == "query_metric" for _, d in events)
    assert any(k == "token" for k, _ in events)


def test_sqlite_session_roundtrip(tmp_path):
    from dataclasses import replace

    from emmerce_agent.infrastructure.config.settings import Settings

    settings = replace(
        Settings.from_env(),
        session_backend="sqlite",
        session_sqlite_path=str(tmp_path / "sessions.db"),
        llm_provider="stub",
    )
    c = build_container(settings)
    tenant = _tenant()
    ses = c.agent.create_session(tenant, shop_id="shop_a1")
    c.agent.chat(ses.session_id, "今日支付GMV是多少", shop_id="shop_a1")
    c2 = build_container(settings)
    loaded = c2.agent.get_session(ses.session_id)
    assert loaded is not None
    assert len(loaded.messages) >= 2
    assert loaded.title.startswith("今日支付")


def test_price_anomaly_finds_extreme_listing():
    c = build_container()
    out = c.gateway.execute(_tenant(), "detect_price_anomaly", {"shop_id": "shop_a1"}).data
    assert out["method"] == "stats_iqr"
    assert out["anomaly_count"] >= 1
    titles = " ".join(a["listing_id"] for a in out["anomalies"])
    assert "L4" in titles


def test_invalid_orders_rules():
    c = build_container()
    out = c.gateway.execute(_tenant(), "flag_invalid_orders", {"shop_id": "shop_a1"}).data
    assert out["invalid_count"] >= 3
    reasons = {tuple(o["reasons"]) for o in out["orders"]}
    flat = {r for o in out["orders"] for r in o["reasons"]}
    assert "status=cancelled" in flat
    assert "duplicate_order_id" in flat


def test_forecast_seasonal_weights():
    c = build_container()
    out = c.gateway.execute(_tenant(), "forecast_sales", {"shop_id": "shop_a1", "horizon": 7}).data
    assert out["ok"] is True
    assert out["method"] == "toy_seasonal_weights"
    assert len(out["forecast"]) == 7
    assert out["baseline_gmv"] > 0


def test_named_workflows():
    c = build_container()
    engine = WorkflowEngine(c.gateway.warehouse)
    tenant = _tenant()
    qc = engine.run("product_qc", tenant, "shop_a1")
    assert qc.ok
    assert [s.name for s in qc.steps] == ["extract_classify_validate", "detect_price_anomaly"]
    ops = engine.run("ops_diagnosis", tenant, "shop_a1")
    assert ops.ok
    assert [s.name for s in ops.steps] == [
        "query_gmv",
        "flag_invalid_orders",
        "detect_price_anomaly",
        "forecast_sales",
        "query_ad_performance",
    ]
    ads = engine.run("ad_diagnosis", tenant, "shop_a1")
    assert ads.ok
    assert [s.name for s in ads.steps] == ["query_ad_performance", "run_ocr_check", "run_alert_scan"]


def test_agent_routes_new_intents():
    c = build_container()
    tenant = _tenant()
    ses = c.agent.create_session(tenant, shop_id="shop_a1")
    resp = c.agent.chat(ses.session_id, "帮我看一下价格异常", shop_id="shop_a1")
    assert resp.status == "completed"
    assert any(b.type == "metric" and b.metric_code == "price_anomaly_count" for b in resp.blocks)


def test_golden_tool_routing():
    path = Path(__file__).resolve().parents[2] / "eval" / "golden_tools.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    llm = StubLLMAdapter()
    hit = 0
    for case in cases:
        out = llm.complete([LLMMessage(role="user", content=case["query"])])
        names = [tc.name for tc in out.tool_calls]
        if any(t in names for t in case["expect_tools"]):
            hit += 1
    assert hit == len(cases), f"eval routing {hit}/{len(cases)}"


def test_order_count_and_refund_rate():
    c = build_container()
    tenant = _tenant()
    orders = c.gateway.execute(tenant, "query_metric", {"shop_id": "shop_a1", "metric_code": "order_count"}).data
    assert orders["value"] == 3
    refund = c.gateway.execute(tenant, "query_metric", {"shop_id": "shop_a1", "metric_code": "refund_rate"}).data
    assert refund["value"] == 0.25


def test_compare_metric_two_days():
    c = build_container()
    out = c.gateway.execute(
        _tenant(),
        "compare_metric",
        {
            "shop_id": "shop_a1",
            "metric_code": "gmv_pay",
            "date_from_a": "2026-08-03",
            "date_to_a": "2026-08-03",
            "date_from_b": "2026-08-04",
            "date_to_b": "2026-08-04",
        },
    ).data
    assert out["value_a"] == 300.0
    assert out["value_b"] == 3500.5
    assert out["delta"] == 3200.5


def test_eval_runner_stub_golden():
    from emmerce_agent.application.eval.runner import run_eval

    report = run_eval()
    assert report.ok, [r.__dict__ for r in report.results if not r.ok]


def test_ad_performance_demo_totals():
    c = build_container()
    out = c.gateway.execute(_tenant(), "query_ad_performance", {"shop_id": "shop_a1"}).data
    assert out["spend"] == 4400.0
    assert out["gmv"] == 3600.0
    assert out["roi"] == 0.8182
    assert out["losing_count"] >= 1
    losing_ids = {x["campaign_id"] for x in out["losing"]}
    assert "AD2" in losing_ids
    spend = c.gateway.execute(_tenant(), "query_metric", {"shop_id": "shop_a1", "metric_code": "ad_spend"}).data
    assert spend["value"] == 4400.0


def test_fake_ocr_flags_listing_mismatch():
    c = build_container()
    out = c.gateway.execute(_tenant(), "run_ocr_check", {"shop_id": "shop_a1"}).data
    assert out["method"] == "fake_ocr"
    assert out["mismatch_count"] >= 1
    by_id = {r["listing_id"]: r for r in out["rows"]}
    assert by_id["L14"]["mismatch"] is True
    assert "积木" in by_id["L14"]["ocr_text"]


def test_alert_scan_and_ack():
    c = build_container()
    tenant = _tenant()
    listed = c.gateway.execute(tenant, "list_alerts", {"shop_id": "shop_a1", "status": "all"}).data
    assert listed["total"] >= 3
    scanned = c.gateway.execute(tenant, "run_alert_scan", {"shop_id": "shop_a1"}).data
    assert scanned["open"] >= 3
    rules = {a["rule"] for a in scanned["alerts"]}
    assert "refund_rate_high" in rules
    assert "ad_roi_low" in rules
    assert "image_text_mismatch" in rules
    target = next(a for a in scanned["alerts"] if a["status"] == "open")
    acked = c.gateway.warehouse.ack_alert(target["id"], tenant_id="tenant_a")
    assert acked is not None and acked.status == "acked"


def test_hashed_bow_embedding_self_similarity():
    from emmerce_agent.application.analytics.embeddings import METHOD, cosine, embed

    assert METHOD == "hashed_bow_v1"
    v = embed("支付GMV口径 成交额")
    assert abs(cosine(v, v) - 1.0) < 1e-9
    assert cosine(v, embed("完全无关的积木玩具")) < cosine(v, embed("支付GMV口径"))
