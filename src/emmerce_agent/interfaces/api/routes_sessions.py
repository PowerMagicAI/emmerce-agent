from __future__ import annotations

import asyncio
import json
import queue as thread_queue
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from emmerce_agent.domain.tenancy import TenantContext
from emmerce_agent.infrastructure.composition import AppContainer
from emmerce_agent.interfaces.api.deps import get_container, get_tenant
from emmerce_agent.interfaces.api.schemas import (
    ApiMessage,
    ChatRequest,
    SessionCreateRequest,
    SessionDetail,
    SessionOut,
)

router = APIRouter(prefix="/api/v1", tags=["sessions"])


def _session_out(st) -> SessionOut:
    return SessionOut(
        session_id=st.session_id,
        title=st.title,
        status=st.status.value if hasattr(st.status, "value") else str(st.status),
        shop_id=st.shop_id,
        created_at=st.created_at.isoformat(),
        updated_at=st.updated_at.isoformat(),
        message_count=len(st.messages),
    )


def _session_detail(st) -> SessionDetail:
    base = _session_out(st)
    messages = [
        ApiMessage(
            role=m.role,
            content=m.content,
            blocks=[b.to_dict() for b in m.blocks],
            run_id=m.run_id,
            created_at=m.created_at.isoformat(),
        )
        for m in st.messages
    ]
    return SessionDetail(**base.model_dump(), messages=messages)


@router.post("/sessions", response_model=SessionOut)
def create_session(
    body: SessionCreateRequest,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    if body.shop_id and body.shop_id not in tenant.shop_ids:
        raise HTTPException(status_code=403, detail=f"无权访问店铺 {body.shop_id}")
    st = container.agent.create_session(tenant, shop_id=body.shop_id, title=body.title)
    return _session_out(st)


@router.get("/sessions")
def list_sessions(
    page: int = 1,
    page_size: int = 20,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    rows = container.agent.list_sessions(tenant.tenant_id, tenant.user_id)
    total = len(rows)
    start = (page - 1) * page_size
    items = [_session_out(s) for s in rows[start : start + page_size]]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: str,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    st = container.agent.get_session(session_id)
    if not st or st.tenant.tenant_id != tenant.tenant_id or st.tenant.user_id != tenant.user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _session_detail(st)


@router.post("/sessions/{session_id}/chat")
def chat(
    session_id: str,
    body: ChatRequest,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    st = container.agent.get_session(session_id)
    if not st or st.tenant.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    st.tenant = tenant
    resp = container.agent.chat(session_id, body.message, shop_id=body.shop_id)
    return resp.to_dict()


@router.post("/sessions/{session_id}/chat/stream")
async def chat_stream(
    session_id: str,
    body: ChatRequest,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    st = container.agent.get_session(session_id)
    if not st or st.tenant.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    st.tenant = tenant

    async def event_gen():
        def sse(event: str, data: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        events: thread_queue.Queue[tuple[str, dict[str, Any]]] = thread_queue.Queue()

        def on_event(kind: str, data: dict[str, Any]) -> None:
            events.put((kind, data))

        task = asyncio.create_task(
            asyncio.to_thread(
                lambda: container.agent.chat(
                    session_id, body.message, shop_id=body.shop_id, on_event=on_event
                )
            )
        )
        try:
            while True:
                while True:
                    try:
                        kind, data = events.get_nowait()
                        event_name = "token" if kind == "token" else "step"
                        yield sse(event_name, data)
                    except thread_queue.Empty:
                        break
                if task.done():
                    while True:
                        try:
                            kind, data = events.get_nowait()
                            event_name = "token" if kind == "token" else "step"
                            yield sse(event_name, data)
                        except thread_queue.Empty:
                            break
                    try:
                        resp = await task
                    except Exception as exc:  # noqa: BLE001 — stream boundary
                        yield sse("error", {"content": str(exc)})
                        break
                    yield sse("result", resp.to_dict())
                    yield sse("done", {"run_id": resp.run_id, "status": resp.status})
                    break
                await asyncio.sleep(0.03)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/sessions/{session_id}/cancel")
def cancel_session(
    session_id: str,
    container: AppContainer = Depends(get_container),
    tenant: TenantContext = Depends(get_tenant),
):
    st = container.agent.get_session(session_id)
    if not st or st.tenant.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    container.agent.cancel(session_id)
    return {"ok": True, "status": "cancelled"}
