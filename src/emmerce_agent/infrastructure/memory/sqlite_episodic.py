"""SQLite-backed episodic memory — survives process restart (single-node)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from emmerce_agent.application.ports import EpisodicMemoryPort, EpisodicRecord
from emmerce_agent.domain.errors import PermissionDenied
from emmerce_agent.infrastructure.memory.stores import _jaccard, _tokenize, _utcnow


class SqliteEpisodicMemory(EpisodicMemoryPort):
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodic (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    shop_ids TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    time_range TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    data_as_of TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 1.0,
                    trusted INTEGER NOT NULL DEFAULT 1,
                    embedding_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_tenant ON episodic(tenant_id, trusted)"
            )
            conn.commit()

    def write(self, record: EpisodicRecord) -> EpisodicRecord:
        if not record.id:
            record.id = f"ep_{uuid.uuid4().hex[:12]}"
        if not record.embedding_text:
            record.embedding_text = f"{record.topic} {record.conclusion} {record.time_range}"
        if record.created_at is None:
            record.created_at = _utcnow()
        created = record.created_at.astimezone(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO episodic (
                    id, tenant_id, user_id, shop_ids, topic, time_range, metrics,
                    conclusion, confidence, data_as_of, importance, trusted,
                    embedding_text, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record.id,
                    record.tenant_id,
                    record.user_id,
                    json.dumps(record.shop_ids, ensure_ascii=False),
                    record.topic,
                    record.time_range,
                    json.dumps(record.metrics, ensure_ascii=False),
                    record.conclusion,
                    record.confidence,
                    record.data_as_of,
                    record.importance,
                    1 if record.trusted else 0,
                    record.embedding_text,
                    created,
                ),
            )
            conn.commit()
        return record

    def delete(self, record_id: str, tenant_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT tenant_id FROM episodic WHERE id=?", (record_id,)).fetchone()
            if not row:
                return False
            if row["tenant_id"] != tenant_id:
                raise PermissionDenied("禁止跨租户删除记忆")
            conn.execute("DELETE FROM episodic WHERE id=?", (record_id,))
            conn.commit()
        return True

    def star(self, record_id: str, tenant_id: str, weight: float = 2.0) -> EpisodicRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM episodic WHERE id=?", (record_id,)).fetchone()
            if not row or row["tenant_id"] != tenant_id:
                raise PermissionDenied("无权标记该记忆")
            conn.execute("UPDATE episodic SET importance=? WHERE id=?", (weight, record_id))
            conn.commit()
            row = conn.execute("SELECT * FROM episodic WHERE id=?", (record_id,)).fetchone()
        return self._row_to_record(row)

    def list_for_tenant(self, tenant_id: str, shop_id: str | None = None) -> list[EpisodicRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM episodic WHERE tenant_id=? AND trusted=1 ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
        out = [self._row_to_record(r) for r in rows]
        if shop_id:
            out = [r for r in out if shop_id in r.shop_ids]
        return out

    def search(
        self, *, tenant_id: str, shop_ids: list[str], query: str, limit: int = 5
    ) -> list[tuple[float, EpisodicRecord]]:
        now = _utcnow()
        from emmerce_agent.application.analytics.embeddings import cosine, embed

        qv = embed(query)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM episodic WHERE tenant_id=? AND trusted=1",
                (tenant_id,),
            ).fetchall()
        scored: list[tuple[float, EpisodicRecord]] = []
        for row in rows:
            rec = self._row_to_record(row)
            if not set(rec.shop_ids) & set(shop_ids):
                continue
            lexical = _jaccard(_tokenize(query), _tokenize(rec.embedding_text))
            semantic = cosine(qv, embed(rec.embedding_text))
            created = rec.created_at or now
            age_hours = max(0.0, (now - created).total_seconds() / 3600.0)
            recency = 1.0 / (1.0 + age_hours / 24.0)
            score = ((0.55 * semantic + 0.45 * lexical) * 0.7 + recency * 0.3) * rec.importance
            if score > 0:
                scored.append((score, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:limit]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> EpisodicRecord:
        created_raw = row["created_at"]
        created = datetime.fromisoformat(created_raw) if created_raw else None
        return EpisodicRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            shop_ids=json.loads(row["shop_ids"] or "[]"),
            topic=row["topic"],
            time_range=row["time_range"],
            metrics=json.loads(row["metrics"] or "[]"),
            conclusion=row["conclusion"],
            confidence=float(row["confidence"]),
            data_as_of=row["data_as_of"],
            importance=float(row["importance"]),
            trusted=bool(row["trusted"]),
            embedding_text=row["embedding_text"],
            created_at=created,
        )
