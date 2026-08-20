"""Application ports (interfaces). Infrastructure implements these."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, runtime_checkable

from emmerce_agent.domain.tenancy import TenantContext
from emmerce_agent.domain.tools.specs import ToolSpec


@dataclass(slots=True)
class LLMMessage:
    role: str  # system|user|assistant|tool
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    name: str | None = None


@dataclass(slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMResponse:
    content: str | None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMPort(Protocol):
    def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse: ...

    def get_model_name(self) -> str: ...


@dataclass(slots=True)
class MetricQueryResult:
    metric_code: str
    value: float
    unit: str
    data_as_of: str
    formula_applied: str
    shop_id: str
    dimensions: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WarehouseRow:
    tenant_id: str
    shop_id: str
    pay_amount: float
    sku: str = ""
    sold_qty: float = 0
    stock_qty: float = 0
    phone: str = ""
    buyer_name: str = ""
    order_id: str = ""
    status: str = "paid"  # paid | refunded | cancelled
    paid_at: str | None = None  # YYYY-MM-DD
    unit_price: float = 0.0
    category: str = ""
    title: str = ""


@dataclass(slots=True)
class ProductListing:
    tenant_id: str
    shop_id: str
    listing_id: str
    title: str
    listed_price: float | None
    listed_category: str = ""
    sku: str = ""
    image_text: str = ""  # 主图 OCR/alt 文本，用于图文一致性检查


@dataclass(slots=True)
class DailySale:
    tenant_id: str
    shop_id: str
    day: str  # YYYY-MM-DD
    gmv: float
    order_count: int


@dataclass(slots=True)
class AdRow:
    tenant_id: str
    shop_id: str
    campaign_id: str
    name: str
    channel: str
    day: str
    spend: float
    clicks: int = 0
    orders: int = 0
    gmv: float = 0.0


@dataclass(slots=True)
class OcrSample:
    listing_id: str
    ocr_text: str
    confidence: float = 0.0


@dataclass(slots=True)
class AlertEvent:
    id: str
    tenant_id: str
    shop_id: str
    severity: str
    rule: str
    message: str
    metric_code: str = ""
    value: float = 0.0
    status: str = "open"
    created_at: str = ""


@runtime_checkable
class WarehousePort(Protocol):
    def query_orders(
        self,
        *,
        tenant_id: str,
        shop_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[WarehouseRow]: ...

    def query_listings(self, *, tenant_id: str, shop_id: str) -> list[ProductListing]: ...

    def query_daily_sales(
        self, *, tenant_id: str, shop_id: str, days: int = 14
    ) -> list[DailySale]: ...

    def query_ads(
        self,
        *,
        tenant_id: str,
        shop_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[AdRow]: ...

    def query_ocr(self) -> list[OcrSample]: ...

    def query_alerts(self, *, tenant_id: str, shop_id: str | None = None) -> list[AlertEvent]: ...

    def replace_alerts(self, events: list[AlertEvent], *, tenant_id: str, shop_id: str) -> None: ...

    def ack_alert(self, alert_id: str, *, tenant_id: str) -> AlertEvent | None: ...


@dataclass(slots=True)
class EpisodicRecord:
    id: str
    tenant_id: str
    user_id: str
    shop_ids: list[str]
    topic: str
    time_range: str
    metrics: list[str]
    conclusion: str
    confidence: float
    data_as_of: str
    importance: float = 1.0
    trusted: bool = True
    embedding_text: str = ""
    created_at: datetime | None = None


@runtime_checkable
class EpisodicMemoryPort(Protocol):
    def write(self, record: EpisodicRecord) -> EpisodicRecord: ...
    def delete(self, record_id: str, tenant_id: str) -> bool: ...
    def star(self, record_id: str, tenant_id: str, weight: float = 2.0) -> EpisodicRecord: ...
    def list_for_tenant(self, tenant_id: str, shop_id: str | None = None) -> list[EpisodicRecord]: ...
    def search(
        self, *, tenant_id: str, shop_ids: list[str], query: str, limit: int = 5
    ) -> list[tuple[float, EpisodicRecord]]: ...


@dataclass(slots=True)
class SemanticDoc:
    id: str
    title: str
    content: str
    metric_codes: list[str] = field(default_factory=list)


@runtime_checkable
class SemanticMemoryPort(Protocol):
    def search(self, query: str, limit: int = 5) -> list[tuple[float, SemanticDoc]]: ...
    def upsert(self, doc: SemanticDoc) -> None: ...


@dataclass(slots=True)
class ExportFile:
    id: str
    tenant_id: str
    user_id: str
    name: str
    created_at: datetime
    expires_at: datetime
    content: bytes
    status: str = "ready"


@runtime_checkable
class ExportStorePort(Protocol):
    def create(self, *, tenant_id: str, user_id: str, name: str, content: bytes) -> ExportFile: ...
    def download(self, file_id: str, *, tenant_id: str, user_id: str, now: datetime | None = None) -> bytes: ...
    def list_for_user(self, *, tenant_id: str, user_id: str) -> list[ExportFile]: ...


@dataclass(slots=True)
class ToolResult:
    ok: bool
    name: str
    data: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None
    # numeric facts extracted for hallucination checks
    numeric_facts: list[dict[str, Any]] = field(default_factory=list)
    # structured UI blocks produced by the tool itself (preferred over name switches)
    blocks: list[Any] = field(default_factory=list)


@runtime_checkable
class ToolGatewayPort(Protocol):
    def execute(self, tenant: TenantContext, name: str, arguments: dict[str, Any]) -> ToolResult: ...
    def list_specs(self) -> list[ToolSpec]: ...
