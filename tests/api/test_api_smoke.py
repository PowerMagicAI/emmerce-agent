"""API smoke against production composition root."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from emmerce_agent.interfaces.api.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _login(client, account: str = "owner") -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"account": account})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["architecture"] == "hexagonal-v2"
    assert body["llm_provider"] == "stub"


def test_api_requires_token(client):
    r = client.get("/api/v1/sessions")
    assert r.status_code == 401
    spoofed = {
        "X-Tenant-Id": "tenant_b",
        "X-User-Id": "hacker",
        "X-Is-Owner": "true",
        "X-Roles": "owner",
        "X-Shop-Ids": "shop_b1",
    }
    assert client.get("/api/v1/me", headers=spoofed).status_code == 401


def test_tools_schema_exposed(client):
    headers = _login(client)
    r = client.get("/api/v1/admin/tools", headers=headers)
    assert r.status_code == 200
    names = {t["function"]["name"] for t in r.json()}
    assert "query_metric" in names
    assert "compare_metric" in names
    assert "ask_clarification" in names
    assert "detect_price_anomaly" in names
    assert "run_workflow" in names
    assert "query_ad_performance" in names
    assert "run_ocr_check" in names
    assert "run_alert_scan" in names
    assert "list_alerts" in names


def test_chat_gmv(client):
    headers = _login(client)
    s = client.post("/api/v1/sessions", json={"shop_id": "shop_a1"}, headers=headers)
    sid = s.json()["session_id"]
    chat = client.post(
        f"/api/v1/sessions/{sid}/chat",
        json={"message": "今日支付GMV是多少", "shop_id": "shop_a1"},
        headers=headers,
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["status"] == "completed"
    assert any(b.get("type") == "metric" and b.get("value") == 3800.5 for b in body["blocks"])
    assert body["meta"]["tenant_id"] == "tenant_a"


def test_traces_require_admin_and_tenant_scope(client):
    analyst = _login(client, "analyst")
    r = client.get("/api/v1/admin/traces/tr_none", headers=analyst)
    assert r.status_code == 403

    ok = client.get("/api/v1/admin/traces/tr_none", headers=_login(client))
    assert ok.status_code == 200
    assert ok.json()["tenant_id"] == "tenant_a"


def test_admin_ops(client):
    assert client.get("/api/v1/admin/ops", headers=_login(client, "analyst")).status_code == 403
    r = client.get("/api/v1/admin/ops", headers=_login(client))
    assert r.status_code == 200
    body = r.json()
    assert "tool_calls" in body
    assert "session_backend" in body


def test_chat_stream_emits_tool_step(client):
    headers = _login(client)
    s = client.post("/api/v1/sessions", json={"shop_id": "shop_a1"}, headers=headers)
    sid = s.json()["session_id"]
    with client.stream(
        "POST",
        f"/api/v1/sessions/{sid}/chat/stream",
        json={"message": "今日支付GMV是多少", "shop_id": "shop_a1"},
        headers=headers,
    ) as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())
    assert "event: step" in text
    assert "event: token" in text
    assert "query_metric" in text
    assert "event: result" in text
    assert "3800.5" in text


def test_sessions_pagination(client):
    headers = _login(client)
    for _ in range(3):
        client.post("/api/v1/sessions", json={"shop_id": "shop_a1"}, headers=headers)
    r = client.get("/api/v1/sessions?page=1&page_size=2", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    assert body["total"] >= 3


def test_alerts_list_scan_ack(client):
    headers = _login(client)
    listed = client.get("/api/v1/alerts?shop_id=shop_a1&status=all", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 3
    scanned = client.post("/api/v1/alerts/scan?shop_id=shop_a1", headers=headers)
    assert scanned.status_code == 200
    body = scanned.json()
    assert body["open"] >= 3
    alert_id = body["alerts"][0]["id"]
    acked = client.post(f"/api/v1/alerts/{alert_id}/ack", headers=headers)
    assert acked.status_code == 200
    assert acked.json()["ok"] is True
