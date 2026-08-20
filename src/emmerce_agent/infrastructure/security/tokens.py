"""HMAC demo session tokens. Identities are issued server-side; client headers are not trusted."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from emmerce_agent.domain.errors import PermissionDenied
from emmerce_agent.domain.tenancy import TenantContext

DEMO_ACCOUNTS: dict[str, dict[str, Any]] = {
    "owner": {
        "tenant_id": "tenant_a",
        "user_id": "user_a_owner",
        "shop_ids": ("shop_a1", "shop_a2"),
        "roles": ("owner",),
        "is_owner": True,
        "channels": ("taobao",),
    },
    "analyst": {
        "tenant_id": "tenant_a",
        "user_id": "user_a_analyst",
        "shop_ids": ("shop_a1",),
        "roles": ("analyst",),
        "is_owner": False,
        "channels": ("taobao",),
    },
}


class TokenError(PermissionDenied):
    code = "AUTH_INVALID"

    def __init__(self, message: str = "登录无效或已过期"):
        super().__init__(message, code="AUTH_INVALID")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_token(tenant: TenantContext, *, secret: str, ttl_hours: int = 12) -> str:
    payload = {
        "tid": tenant.tenant_id,
        "uid": tenant.user_id,
        "shops": list(tenant.shop_ids),
        "roles": list(tenant.roles),
        "own": tenant.is_owner,
        "ch": list(tenant.channels),
        "exp": int(time.time()) + max(1, ttl_hours) * 3600,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"v1.{body}.{sig}"


def verify_token(token: str, secret: str) -> TenantContext:
    parts = (token or "").split(".")
    if len(parts) != 3 or parts[0] != "v1":
        raise TokenError()
    body, sig = parts[1], parts[2]
    expect = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        raise TokenError()
    try:
        payload = json.loads(_unb64(body).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenError() from exc
    if int(payload.get("exp") or 0) < int(time.time()):
        raise TokenError("登录已过期，请重新选择身份")
    return TenantContext(
        tenant_id=str(payload["tid"]),
        user_id=str(payload["uid"]),
        shop_ids=tuple(payload.get("shops") or ()),
        roles=tuple(payload.get("roles") or ()),
        is_owner=bool(payload.get("own")),
        channels=tuple(payload.get("ch") or ("taobao",)),
    )


def tenant_for_account(account: str) -> TenantContext:
    row = DEMO_ACCOUNTS.get((account or "").strip().lower())
    if not row:
        raise TokenError("未知演示账号，请使用 owner 或 analyst")
    return TenantContext(
        tenant_id=row["tenant_id"],
        user_id=row["user_id"],
        shop_ids=row["shop_ids"],
        roles=row["roles"],
        is_owner=row["is_owner"],
        channels=row["channels"],
    )
