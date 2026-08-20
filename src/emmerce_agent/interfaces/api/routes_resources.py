from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from emmerce_agent.application.workflow.engine import WorkflowEngine
from emmerce_agent.domain.errors import ToolExecutionError
from emmerce_agent.domain.tenancy import TenantContext
from emmerce_agent.infrastructure.composition import AppContainer
from emmerce_agent.infrastructure.security.tokens import TokenError, issue_token, tenant_for_account
from emmerce_agent.interfaces.api.deps import get_container, get_tenant, require_admin
from emmerce_agent.interfaces.api.schemas import (
    ContextConfigUpdate,
    FeatureFlagsUpdate,
    FeedbackRequest,
    LoginRequest,
)

router = APIRouter(prefix="/api/v1", tags=["resources"])


@router.post("/auth/login")
def login(body: LoginRequest, container: AppContainer = Depends(get_container)):
    try:
        tenant = tenant_for_account(body.account)
    except TokenError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    token = issue_token(
        tenant,
        secret=container.settings.auth_secret,
        ttl_hours=container.settings.auth_ttl_hours,
    )
    return {
        "token": token,
        "account": body.account.strip().lower(),
        "expires_in_hours": container.settings.auth_ttl_hours,
        "tenant_id": tenant.tenant_id,
        "user_id": tenant.user_id,
        "shop_ids": list(tenant.shop_ids),
        "roles": list(tenant.roles),
        "is_owner": tenant.is_owner,
        "is_admin": tenant.is_admin(),
    }


@router.get("/memories")
def list_memories(
    shop_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    rows = container.agent.episodic.list_for_tenant(tenant.tenant_id, shop_id=shop_id)
    total = len(rows)
    start = (page - 1) * page_size
    slice_rows = rows[start : start + page_size]
    items = [
        {
            "id": r.id,
            "topic": r.topic,
            "conclusion": r.conclusion,
            "time_range": r.time_range,
            "shop_ids": r.shop_ids,
            "metrics": r.metrics,
            "importance": r.importance,
            "data_as_of": r.data_as_of,
            "created_at": (r.created_at.isoformat() if r.created_at else None),
            "trusted": r.trusted,
            "confidence": getattr(r, "confidence", None),
        }
        for r in slice_rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.delete("/memories/{memory_id}")
def delete_memory(
    memory_id: str,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    ok = container.agent.episodic.delete(memory_id, tenant.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True}


@router.post("/memories/{memory_id}/star")
def star_memory(
    memory_id: str,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    rec = container.agent.episodic.star(memory_id, tenant.tenant_id, weight=2.5)
    return {"id": rec.id, "importance": rec.importance}


@router.get("/exports")
def list_exports(
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    files = container.exports.list_for_user(tenant_id=tenant.tenant_id, user_id=tenant.user_id)
    return [
        {
            "id": f.id,
            "name": f.name,
            "status": f.status,
            "created_at": f.created_at.isoformat(),
            "expires_at": f.expires_at.isoformat(),
            "download_url": f"/api/v1/exports/{f.id}/download",
        }
        for f in files
    ]


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: str,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    try:
        data = container.exports.download(
            export_id, tenant_id=tenant.tenant_id, user_id=tenant.user_id
        )
    except ToolExecutionError as e:
        status = 404 if e.code == "EXPORT_NOT_FOUND" else 403 if e.code == "EXPORT_FORBIDDEN" else 410
        raise HTTPException(status_code=status, detail=e.message) from e
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{export_id}.xlsx"'},
    )


@router.get("/metrics/dictionary")
def metrics_dictionary(container: AppContainer = Depends(get_container)):
    return [
        {
            "metric_code": m.metric_code,
            "name": m.name,
            "aliases": list(m.aliases),
            "formula": m.formula,
            "grain": m.grain,
            "latency": m.latency,
            "channels": list(m.channels),
            "common_misuse": m.common_misuse,
            "version": m.version,
        }
        for m in container.catalog.list_all()
    ]


@router.post("/feedback")
def feedback(
    body: FeedbackRequest,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    container.agent.submit_feedback(
        body.session_id,
        thumbs_down=body.thumbs_down,
        error_type=body.error_type,
    )
    container.feedback_log.append(
        {"tenant_id": tenant.tenant_id, "user_id": tenant.user_id, **body.model_dump()}
    )
    return {"ok": True}


@router.get("/admin/traces/{trace_id}")
def get_trace(
    trace_id: str,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    require_admin(tenant)
    hits = container.agent.audit.find_by_trace(trace_id, tenant_id=tenant.tenant_id)
    return {"trace_id": trace_id, "tenant_id": tenant.tenant_id, "events": hits}


@router.get("/admin/context-config")
def get_context_config(
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    require_admin(tenant)
    c = container.context_config
    return {
        "max_tokens": c.max_tokens,
        "system_reserve_ratio": c.system_reserve_ratio,
        "system_max_packets": getattr(c, "system_max_packets", 3),
        "min_relevance": c.min_relevance,
        "w_relevance": c.w_relevance,
        "w_recency": c.w_recency,
        "enable_compress": c.enable_compress,
        "detail_top_n": c.detail_top_n,
        "heavy_compress": c.heavy_compress,
    }


@router.put("/admin/context-config")
def put_context_config(
    body: ContextConfigUpdate,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    require_admin(tenant)
    c = container.context_config
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    container.agent.context_builder.config = c
    return get_context_config(container, tenant)


@router.get("/admin/feature-flags")
def get_flags(
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    require_admin(tenant)
    f = container.flags
    return {
        "memory_enabled": f.memory_enabled,
        "rag_enabled": f.rag_enabled,
        "inventory_tool_enabled": f.inventory_tool_enabled,
        "order_tool_enabled": f.order_tool_enabled,
        "export_tool_enabled": f.export_tool_enabled,
        "analytics_tool_enabled": f.analytics_tool_enabled,
        "ads_tool_enabled": f.ads_tool_enabled,
        "alert_tool_enabled": f.alert_tool_enabled,
    }


@router.put("/admin/feature-flags")
def put_flags(
    body: FeatureFlagsUpdate,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    require_admin(tenant)
    f = container.flags
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(f, k, v)
    return get_flags(container, tenant)


@router.get("/admin/ops")
def get_ops(
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    require_admin(tenant)
    snap = container.ops.snapshot()
    snap["dataset"] = str(getattr(container.settings, "dataset_dir", "") or "datasets/demo")
    snap["session_backend"] = container.settings.session_backend
    return snap


@router.get("/admin/tools")
def list_tools(
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    """Expose tool JSON Schemas for ops / debugging."""
    require_admin(tenant)
    return [s.openai_tool() for s in container.gateway.list_specs()]


@router.post("/pipeline/run")
def run_pipeline(
    shop_id: str = "shop_a1",
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    tenant.ensure_shop_access(shop_id)
    result = container.gateway.execute(tenant, "run_product_pipeline", {"shop_id": shop_id})
    return {"ok": result.ok, "data": result.data}


@router.post("/workflows/{name}/run")
def run_workflow(
    name: str,
    shop_id: str = "shop_a1",
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    tenant.ensure_shop_access(shop_id)
    engine = WorkflowEngine(container.gateway.warehouse)
    result = engine.run(name, tenant, shop_id)
    return WorkflowEngine.to_dict(result)


@router.get("/alerts")
def list_alerts(
    shop_id: str = "shop_a1",
    status: str = "open",
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    tenant.ensure_shop_access(shop_id)
    args: dict = {"shop_id": shop_id}
    if status:
        args["status"] = status if status in {"open", "acked", "all"} else "open"
    return container.gateway.execute(tenant, "list_alerts", args).data


@router.post("/alerts/scan")
def scan_alerts_api(
    shop_id: str = "shop_a1",
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    tenant.ensure_shop_access(shop_id)
    return container.gateway.execute(tenant, "run_alert_scan", {"shop_id": shop_id}).data


@router.post("/alerts/{alert_id}/ack")
def ack_alert(
    alert_id: str,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    row = container.gateway.warehouse.ack_alert(alert_id, tenant_id=tenant.tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="预警不存在")
    return {"ok": True, "id": row.id, "status": row.status}


@router.get("/me")
def me(tenant: TenantContext = Depends(get_tenant)):
    return {
        "tenant_id": tenant.tenant_id,
        "user_id": tenant.user_id,
        "shop_ids": list(tenant.shop_ids),
        "roles": list(tenant.roles),
        "is_owner": tenant.is_owner,
        "channels": list(tenant.channels),
        "is_admin": tenant.is_admin(),
    }
