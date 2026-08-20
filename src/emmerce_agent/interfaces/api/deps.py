from __future__ import annotations

from fastapi import Header, HTTPException, Request

from emmerce_agent.domain.errors import PermissionDenied
from emmerce_agent.domain.tenancy import TenantContext
from emmerce_agent.infrastructure.composition import AppContainer
from emmerce_agent.infrastructure.security.tokens import TokenError, verify_token


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_tenant(
    request: Request,
    authorization: str | None = Header(default=None),
) -> TenantContext:
    """Identity comes from a signed token. Spoofable X-Tenant-* headers are ignored."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="需要登录")
    token = authorization.split(" ", 1)[1].strip()
    secret = get_container(request).settings.auth_secret
    try:
        return verify_token(token, secret)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=exc.message) from exc


def require_admin(tenant: TenantContext) -> TenantContext:
    if not tenant.is_admin():
        raise PermissionDenied("需要管理员权限")
    return tenant
