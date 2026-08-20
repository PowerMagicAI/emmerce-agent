"""Episodic / Semantic memory implementations."""

from __future__ import annotations

import re
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from emmerce_agent.application.ports import EpisodicMemoryPort, EpisodicRecord, SemanticDoc, SemanticMemoryPort
from emmerce_agent.domain.errors import PermissionDenied


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _tokenize(text: str) -> set[str]:
    text = text.lower()
    tokens: set[str] = set(re.findall(r"[a-z0-9_]+", text))
    cn = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.update(cn)
    for i in range(len(cn) - 1):
        tokens.add(cn[i] + cn[i + 1])
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class WorkingItem:
    key: str
    content: str
    created_at: datetime = field(default_factory=_utcnow)


class WorkingMemory:
    def __init__(self, capacity: int = 50, ttl_minutes: int = 60):
        self.capacity = capacity
        self.ttl = timedelta(minutes=ttl_minutes)
        self._items: OrderedDict[str, WorkingItem] = OrderedDict()

    def put(self, key: str, content: str) -> None:
        self._purge()
        if key in self._items:
            del self._items[key]
        self._items[key] = WorkingItem(key=key, content=content)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)

    def get(self, key: str) -> str | None:
        self._purge()
        item = self._items.get(key)
        return item.content if item else None

    def clear(self) -> None:
        self._items.clear()

    def _purge(self) -> None:
        now = _utcnow()
        for k in [k for k, v in self._items.items() if now - v.created_at > self.ttl]:
            del self._items[k]


class InMemoryEpisodicMemory(EpisodicMemoryPort):
    def __init__(self) -> None:
        self._store: dict[str, EpisodicRecord] = {}

    def write(self, record: EpisodicRecord) -> EpisodicRecord:
        if not record.id:
            record.id = f"ep_{uuid.uuid4().hex[:12]}"
        if not record.embedding_text:
            record.embedding_text = f"{record.topic} {record.conclusion} {record.time_range}"
        if record.created_at is None:
            record.created_at = _utcnow()
        self._store[record.id] = record
        return record

    def delete(self, record_id: str, tenant_id: str) -> bool:
        rec = self._store.get(record_id)
        if not rec:
            return False
        if rec.tenant_id != tenant_id:
            raise PermissionDenied("禁止跨租户删除记忆")
        del self._store[record_id]
        return True

    def star(self, record_id: str, tenant_id: str, weight: float = 2.0) -> EpisodicRecord:
        rec = self._store.get(record_id)
        if not rec or rec.tenant_id != tenant_id:
            raise PermissionDenied("无权标记该记忆")
        rec.importance = weight
        return rec

    def list_for_tenant(self, tenant_id: str, shop_id: str | None = None) -> list[EpisodicRecord]:
        rows = [r for r in self._store.values() if r.tenant_id == tenant_id and r.trusted]
        if shop_id:
            rows = [r for r in rows if shop_id in r.shop_ids]
        return sorted(rows, key=lambda r: r.created_at or _utcnow(), reverse=True)

    def search(
        self, *, tenant_id: str, shop_ids: list[str], query: str, limit: int = 5
    ) -> list[tuple[float, EpisodicRecord]]:
        now = _utcnow()
        from emmerce_agent.application.analytics.embeddings import cosine, embed

        qv = embed(query)
        scored: list[tuple[float, EpisodicRecord]] = []
        for rec in self._store.values():
            if rec.tenant_id != tenant_id or not rec.trusted:
                continue
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


class InMemorySemanticMemory(SemanticMemoryPort):
    def __init__(self) -> None:
        self._docs: dict[str, SemanticDoc] = {}

    def upsert(self, doc: SemanticDoc) -> None:
        if "订单号:" in doc.content or "买家手机" in doc.content:
            raise ValueError("SemanticMemory 禁止写入商家私有数据")
        self._docs[doc.id] = doc

    def search(self, query: str, limit: int = 5) -> list[tuple[float, SemanticDoc]]:
        from emmerce_agent.application.analytics.embeddings import cosine, embed

        qv = embed(query)
        scored = []
        for doc in self._docs.values():
            text = doc.title + " " + doc.content
            lexical = _jaccard(_tokenize(query), _tokenize(text))
            score = 0.55 * cosine(qv, embed(text)) + 0.45 * lexical
            if score >= 0.08:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:limit]


def seed_semantic(semantic: InMemorySemanticMemory) -> None:
    semantic.upsert(
        SemanticDoc(
            id="sem_gmv",
            title="支付GMV口径",
            content="支付GMV(gmv_pay)=统计期内支付成功订单金额合计，不含未支付；别名成交额。有效订单量不计 0 元/取消单。",
            metric_codes=["gmv_pay"],
        )
    )
    semantic.upsert(
        SemanticDoc(
            id="sem_stock",
            title="库存安全阈值",
            content="库存安全阈值：周转天数>60且近30天销量<=5视为滞销；补货需结合安全库存下限。",
            metric_codes=["sell_through_rate", "slow_moving_count"],
        )
    )
    semantic.upsert(
        SemanticDoc(
            id="sem_ad_roi",
            title="广告ROI口径",
            content="广告ROI=投放带来的GMV/广告花费，数字来自广告表聚合；不要把广告GMV加进支付GMV。",
            metric_codes=["ad_roi", "ad_spend"],
        )
    )
