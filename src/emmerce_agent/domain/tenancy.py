"""Multi-tenant identity context — never trust client shop_id without this."""

from __future__ import annotations

from dataclasses import dataclass

from emmerce_agent.domain.errors import PermissionDenied


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: str
    user_id: str
    shop_ids: tuple[str, ...]
    roles: tuple[str, ...]
    is_owner: bool = False
    channels: tuple[str, ...] = ("taobao",)

    def ensure_shop_access(self, shop_id: str) -> None:
        if shop_id not in self.shop_ids:
            raise PermissionDenied(f"无权访问店铺 {shop_id}")

    def ensure_same_tenant(self, other_tenant_id: str) -> None:
        if other_tenant_id != self.tenant_id:
            raise PermissionDenied("禁止跨租户访问")

    def is_admin(self) -> bool:
        """Ops / owner only — used for admin traces and config endpoints."""
        return self.is_owner or "admin" in self.roles or "ops" in self.roles
