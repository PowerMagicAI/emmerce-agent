from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    account: str = Field(description="演示身份 owner|analyst")


class SessionCreateRequest(BaseModel):
    shop_id: str | None = None
    title: str = "新对话"


class SessionOut(BaseModel):
    session_id: str
    title: str
    status: str
    shop_id: str | None = None
    created_at: str
    updated_at: str
    message_count: int = 0


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    shop_id: str | None = None


class FeedbackRequest(BaseModel):
    session_id: str
    thumbs_up: bool = False
    thumbs_down: bool = False
    error_type: str | None = None
    comment: str | None = None


class ContextConfigUpdate(BaseModel):
    max_tokens: int | None = None
    system_reserve_ratio: float | None = None
    system_max_packets: int | None = None
    min_relevance: float | None = None
    w_relevance: float | None = None
    w_recency: float | None = None
    enable_compress: bool | None = None
    detail_top_n: int | None = None
    heavy_compress: bool | None = None


class FeatureFlagsUpdate(BaseModel):
    memory_enabled: bool | None = None
    rag_enabled: bool | None = None
    inventory_tool_enabled: bool | None = None
    order_tool_enabled: bool | None = None
    export_tool_enabled: bool | None = None
    analytics_tool_enabled: bool | None = None
    ads_tool_enabled: bool | None = None
    alert_tool_enabled: bool | None = None


class ApiMessage(BaseModel):
    role: str
    content: str
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    run_id: str | None = None
    created_at: str


class SessionDetail(SessionOut):
    messages: list[ApiMessage] = Field(default_factory=list)
