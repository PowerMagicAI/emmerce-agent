"""Export file store."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from emmerce_agent.application.ports import ExportFile, ExportStorePort
from emmerce_agent.domain.errors import ToolExecutionError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryExportStore(ExportStorePort):
    def __init__(self, ttl_hours: int = 24):
        self.ttl_hours = ttl_hours
        self._files: dict[str, ExportFile] = {}

    def create(self, *, tenant_id: str, user_id: str, name: str, content: bytes) -> ExportFile:
        fid = f"exp_{uuid.uuid4().hex[:12]}"
        now = _utcnow()
        f = ExportFile(
            id=fid,
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            created_at=now,
            expires_at=now + timedelta(hours=self.ttl_hours),
            content=content,
        )
        self._files[fid] = f
        return f

    def download(
        self, file_id: str, *, tenant_id: str, user_id: str, now: datetime | None = None
    ) -> bytes:
        now = now or _utcnow()
        f = self._files.get(file_id)
        if not f:
            raise ToolExecutionError("文件不存在", code="EXPORT_NOT_FOUND")
        if f.tenant_id != tenant_id or f.user_id != user_id:
            raise ToolExecutionError("无权下载该文件", code="EXPORT_FORBIDDEN")
        if now >= f.expires_at:
            raise ToolExecutionError("下载链接已过期", code="EXPORT_EXPIRED")
        return f.content

    def list_for_user(self, *, tenant_id: str, user_id: str) -> list[ExportFile]:
        rows = [f for f in self._files.values() if f.tenant_id == tenant_id and f.user_id == user_id]
        return sorted(rows, key=lambda f: f.created_at, reverse=True)
