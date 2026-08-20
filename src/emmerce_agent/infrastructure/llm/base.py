"""LLM adapters — normalize vendor tool_call formats to LLMResponse."""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable
from urllib import error as urlerror
from urllib import request as urlrequest

from emmerce_agent.application.ports import LLMMessage, LLMResponse, LLMToolCall
from emmerce_agent.domain.errors import DomainError, ToolExecutionError
from emmerce_agent.domain.tools.specs import ToolSpec


class LLMProviderError(DomainError):
    code = "LLM_PROVIDER_ERROR"


class BaseLLMAdapter(ABC):
    model_name: str = "unknown"

    @abstractmethod
    def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse: ...

    def get_model_name(self) -> str:
        return self.model_name

    @staticmethod
    def _parse_arguments(raw: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """Shared HTTP client for OpenAI-compatible endpoints (Qwen / Zhipu / ModelScope / …)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 120,
        extra_body: dict[str, Any] | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.timeout = timeout
        self.extra_body = dict(extra_body or {})

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": self._to_vendor_messages(messages),
        }
        if tools:
            payload["tools"] = [t.openai_tool() for t in tools]
            payload["tool_choice"] = tool_choice
        if self.extra_body:
            payload.update(self.extra_body)
        payload["stream"] = bool(on_delta)

        if payload.get("stream"):
            try:
                return self._complete_stream(payload, on_delta)
            except LLMProviderError:
                payload["stream"] = False
                return self._complete_json(payload)
        return self._complete_json(payload)

    def _request(self, payload: dict[str, Any]):
        req = urlrequest.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            return urlrequest.urlopen(req, timeout=self.timeout)
        except urlerror.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            detail = err_body[:500]
            try:
                parsed = json.loads(err_body)
                detail = (
                    (parsed.get("error") or {}).get("message")
                    or parsed.get("message")
                    or detail
                )
            except json.JSONDecodeError:
                pass
            if e.code == 429:
                raise ToolExecutionError(
                    f"模型服务限流或额度不足: {detail}",
                    code="LLM_RATE_LIMITED",
                    retryable=True,
                ) from e
            raise LLMProviderError(f"模型调用失败 HTTP {e.code}: {detail}") from e
        except urlerror.URLError as e:
            raise LLMProviderError(f"模型服务不可达: {e.reason}") from e

    def _complete_json(self, payload: dict[str, Any]) -> LLMResponse:
        with self._request(payload) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return self._parse_completion(body)

    def _complete_stream(self, payload: dict[str, Any], on_delta: Callable[[str], None] | None) -> LLMResponse:
        content_parts: list[str] = []
        tool_acc: dict[int, dict[str, str]] = {}
        last_usage: dict[str, Any] = {}
        model = self.model_name
        with self._request(payload) as resp:
            buf = b""
            while True:
                chunk = resp.read(256)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        evt = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if evt.get("model"):
                        model = evt["model"]
                    if evt.get("usage"):
                        last_usage = evt["usage"]
                    choices = evt.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0] or {}).get("delta") or {}
                    piece = delta.get("content")
                    if piece:
                        content_parts.append(piece)
                        if on_delta:
                            on_delta(piece)
                    for tc in delta.get("tool_calls") or []:
                        idx = int(tc.get("index") or 0)
                        slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
        tool_calls = [
            LLMToolCall(
                id=slot["id"] or f"call_{uuid.uuid4().hex[:8]}",
                name=slot["name"],
                arguments=self._parse_arguments(slot["arguments"] or "{}"),
            )
            for _, slot in sorted(tool_acc.items())
            if slot["name"]
        ]
        content = "".join(content_parts) or None
        raw = {"model": model, "usage": last_usage, "stream": True}
        return LLMResponse(content=content, tool_calls=tool_calls, model=model, raw=raw)

    def _parse_completion(self, body: dict[str, Any]) -> LLMResponse:
        choices = body.get("choices")
        if not choices:
            raise LLMProviderError(
                "模型返回空结果（choices 为空）。常见原因：免费额度用尽、限流或模型暂时不可用。"
            )

        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )

        tool_calls: list[LLMToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            tool_calls.append(
                LLMToolCall(
                    id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                    name=fn.get("name") or "",
                    arguments=self._parse_arguments(fn.get("arguments") or "{}"),
                )
            )
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=body.get("model") or self.model_name,
            raw=body,
        )

    @staticmethod
    def _to_vendor_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            item: dict[str, Any] = {"role": m.role}
            if m.content is not None:
                item["content"] = m.content
            if m.tool_call_id:
                item["tool_call_id"] = m.tool_call_id
            if m.name:
                item["name"] = m.name
            if m.tool_calls:
                item["tool_calls"] = m.tool_calls
            out.append(item)
        return out


class QwenAdapter(OpenAICompatibleAdapter):
    def __init__(self, *, api_key: str, model: str = "qwen-plus", base_url: str = ""):
        super().__init__(
            api_key=api_key,
            base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            model=model,
        )


class ZhipuAdapter(OpenAICompatibleAdapter):
    def __init__(self, *, api_key: str, model: str = "glm-4", base_url: str = ""):
        super().__init__(
            api_key=api_key,
            base_url=base_url or "https://open.bigmodel.cn/api/paas/v4",
            model=model,
        )


class ModelScopeAdapter(OpenAICompatibleAdapter):
    """ModelScope OpenAI-compatible inference (e.g. deepseek-ai/DeepSeek-V4-Pro)."""

    DEFAULT_BASE = "https://api-inference.modelscope.cn/v1"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-ai/DeepSeek-V4-Pro",
        base_url: str = "",
        enable_thinking: bool = False,
    ):
        extra: dict[str, Any] = {}
        # Prefer non-thinking for lower latency / quota on free tier; override via env if needed
        if not enable_thinking:
            extra["enable_thinking"] = False
        super().__init__(
            api_key=api_key,
            base_url=base_url or self.DEFAULT_BASE,
            model=model,
            timeout=180,
            extra_body=extra,
        )


class OpenAICompatAdapter(OpenAICompatibleAdapter):
    """Generic OpenAI-compatible provider (any base_url + model)."""

    def __init__(self, *, api_key: str, model: str, base_url: str):
        if not base_url:
            raise ValueError("EMMERCE_LLM_BASE_URL is required for openai provider")
        super().__init__(api_key=api_key, base_url=base_url, model=model, timeout=120)
