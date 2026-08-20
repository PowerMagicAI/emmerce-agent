"""SQLite session persistence (optional). In-memory orchestrator dict remains the cache."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from emmerce_agent.application.agent.orchestrator import ChatMessage, SessionState
from emmerce_agent.domain.messaging import MessageBlock, SessionStatus
from emmerce_agent.domain.tenancy import TenantContext


def _dt(v: str | None) -> datetime:
    if not v:
        from emmerce_agent.domain.context import utcnow

        return utcnow()
    return datetime.fromisoformat(v)


class SqliteSessionStore:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, st: SessionState) -> None:
        payload = json.dumps(_session_to_dict(st), ensure_ascii=False, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions (session_id, tenant_id, user_id, payload)
                VALUES (?,?,?,?)
                """,
                (st.session_id, st.tenant.tenant_id, st.tenant.user_id, payload),
            )
            conn.commit()

    def load(self, session_id: str) -> SessionState | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            return None
        return _session_from_dict(json.loads(row["payload"]))

    def load_all(self) -> list[SessionState]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM sessions").fetchall()
        return [_session_from_dict(json.loads(r["payload"])) for r in rows]


def _session_to_dict(st: SessionState) -> dict[str, Any]:
    t = st.tenant
    return {
        "session_id": st.session_id,
        "tenant": {
            "tenant_id": t.tenant_id,
            "user_id": t.user_id,
            "shop_ids": list(t.shop_ids),
            "roles": list(t.roles),
            "is_owner": t.is_owner,
            "channels": list(t.channels),
        },
        "status": st.status.value,
        "cancelled": st.cancelled,
        "writes_blocked": st.writes_blocked,
        "title": st.title,
        "created_at": st.created_at.isoformat(),
        "updated_at": st.updated_at.isoformat(),
        "shop_id": st.shop_id,
        "last_run_id": st.last_run_id,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "blocks": [b.to_dict() for b in m.blocks],
                "run_id": m.run_id,
                "created_at": m.created_at.isoformat(),
            }
            for m in st.messages
        ],
    }


def _session_from_dict(d: dict[str, Any]) -> SessionState:
    t = d["tenant"]
    tenant = TenantContext(
        tenant_id=t["tenant_id"],
        user_id=t["user_id"],
        shop_ids=tuple(t.get("shop_ids") or ()),
        roles=tuple(t.get("roles") or ()),
        is_owner=bool(t.get("is_owner")),
        channels=tuple(t.get("channels") or ("taobao",)),
    )
    messages = []
    for m in d.get("messages") or []:
        blocks = [MessageBlock(**{k: v for k, v in b.items() if k in MessageBlock.__dataclass_fields__}) for b in m.get("blocks") or []]
        messages.append(
            ChatMessage(
                role=m["role"],
                content=m.get("content") or "",
                blocks=blocks,
                run_id=m.get("run_id"),
                created_at=_dt(m.get("created_at")),
            )
        )
    return SessionState(
        session_id=d["session_id"],
        tenant=tenant,
        status=SessionStatus(d.get("status") or "idle"),
        cancelled=bool(d.get("cancelled")),
        writes_blocked=bool(d.get("writes_blocked")),
        title=d.get("title") or "新对话",
        created_at=_dt(d.get("created_at")),
        updated_at=_dt(d.get("updated_at")),
        messages=messages,
        shop_id=d.get("shop_id"),
        last_run_id=d.get("last_run_id"),
    )
