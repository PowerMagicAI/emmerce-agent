"""Production agent orchestrator: LLM tool loop + grounding validation."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from emmerce_agent.application.agent.block_composer import BlockComposer
from emmerce_agent.application.agent.memory_writer import EpisodicMemoryWriter
from emmerce_agent.application.agent.prompts import FINAL_ANSWER_INSTRUCTION, build_system_prompt
from emmerce_agent.application.agent.result_validator import ResultValidator
from emmerce_agent.application.agent.token_budget import (
    TurnTokenBudget,
    estimate_messages_tokens,
    estimate_text_tokens,
    estimate_tool_result_tokens,
)
from emmerce_agent.application.audit import AuditBuffer
from emmerce_agent.application.ops import OpsCollector
from emmerce_agent.application.ports import (
    EpisodicMemoryPort,
    LLMMessage,
    LLMPort,
    SemanticMemoryPort,
    ToolGatewayPort,
    ToolResult,
)
from emmerce_agent.domain.context import ContextBuilder, ContextConfig, ContextPacket, SourceType, utcnow
from emmerce_agent.domain.errors import (
    DomainError,
    HallucinationDetected,
    PermissionDenied,
    ToolExecutionError,
    TurnBudgetExceeded,
)
from emmerce_agent.domain.messaging import (
    AgentTurnResult,
    BlockType,
    MessageBlock,
    ResponseMeta,
    SessionStatus,
)
from emmerce_agent.domain.metrics.catalog import MetricCatalog
from emmerce_agent.domain.security.injection import PromptInjectionDetector
from emmerce_agent.domain.tenancy import TenantContext
from emmerce_agent.infrastructure.memory.stores import WorkingMemory


@dataclass
class ChatMessage:
    role: str
    content: str
    blocks: list[MessageBlock] = field(default_factory=list)
    run_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class SessionState:
    session_id: str
    tenant: TenantContext
    status: SessionStatus = SessionStatus.IDLE
    cancelled: bool = False
    writes_blocked: bool = False
    title: str = "新对话"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    messages: list[ChatMessage] = field(default_factory=list)
    shop_id: str | None = None
    last_run_id: str | None = None


class AgentOrchestrator:
    """
    Production loop:
      context → LLM(+tools schema) → gateway.execute → ... → final LLM → validate → blocks
    """

    def __init__(
        self,
        *,
        llm: LLMPort,
        tools: ToolGatewayPort,
        catalog: MetricCatalog,
        episodic: EpisodicMemoryPort,
        semantic: SemanticMemoryPort,
        context_builder: ContextBuilder | None = None,
        validator: ResultValidator | None = None,
        max_tool_rounds: int = 8,
        max_turn_tokens: int = 32_000,
        data_as_of: str = "2026-08-04T08:00:00+08:00",
        audit_maxlen: int = 2000,
        injection_detector: PromptInjectionDetector | None = None,
        ops: OpsCollector | None = None,
        session_store: Any = None,
        working: WorkingMemory | None = None,
    ):
        self.llm = llm
        self.tools = tools
        self.catalog = catalog
        self.episodic = episodic
        self.semantic = semantic
        self.context_builder = context_builder or ContextBuilder(ContextConfig())
        self.validator = validator or ResultValidator(strict_text_numbers=True)
        self.max_tool_rounds = max_tool_rounds
        self.max_turn_tokens = max_turn_tokens
        self.data_as_of = data_as_of
        self.sessions: dict[str, SessionState] = {}
        self.audit = AuditBuffer(maxlen=audit_maxlen)
        self.block_composer = BlockComposer(data_as_of=data_as_of)
        self.memory_writer = EpisodicMemoryWriter(episodic)
        self.injection_detector = injection_detector or PromptInjectionDetector()
        self._feedback_wrong_data: set[str] = set()
        self.ops = ops or OpsCollector()
        self.session_store = session_store
        self.working = working or WorkingMemory()
        self._on_event: Callable[[str, dict[str, Any]], None] | None = None
        if self.session_store is not None and hasattr(self.session_store, "load_all"):
            for loaded in self.session_store.load_all():
                self.sessions[loaded.session_id] = loaded

    # —— session CRUD ——
    def create_session(
        self, tenant: TenantContext, *, shop_id: str | None = None, title: str = "新对话"
    ) -> SessionState:
        sid = f"ses_{uuid.uuid4().hex[:10]}"
        st = SessionState(
            session_id=sid,
            tenant=tenant,
            title=title,
            shop_id=shop_id or (tenant.shop_ids[0] if tenant.shop_ids else None),
        )
        self.sessions[sid] = st
        self._persist(st)
        return st

    def list_sessions(self, tenant_id: str, user_id: str) -> list[SessionState]:
        rows = [
            s
            for s in self.sessions.values()
            if s.tenant.tenant_id == tenant_id and s.tenant.user_id == user_id
        ]
        return sorted(rows, key=lambda s: s.updated_at, reverse=True)

    def get_session(self, session_id: str) -> SessionState | None:
        st = self.sessions.get(session_id)
        if st:
            return st
        if self.session_store is not None and hasattr(self.session_store, "load"):
            loaded = self.session_store.load(session_id)
            if loaded:
                self.sessions[session_id] = loaded
                return loaded
        return None

    def _persist(self, st: SessionState) -> None:
        if self.session_store is not None:
            try:
                self.session_store.save(st)
            except Exception:
                pass

    def _emit(self, event: str, content: str, **extra: Any) -> None:
        if self._on_event:
            self._on_event(event, {"content": content, "event": event, **extra})

    def cancel(self, session_id: str) -> None:
        st = self.sessions[session_id]
        st.cancelled = True
        st.status = SessionStatus.CANCELLED
        st.writes_blocked = True
        self._persist(st)

    def submit_feedback(self, session_id: str, *, thumbs_down: bool, error_type: str | None = None) -> None:
        if thumbs_down and error_type == "data_error":
            self._feedback_wrong_data.add(session_id)

    def chat(
        self,
        session_id: str,
        user_text: str,
        *,
        shop_id: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> AgentTurnResult:
        st = self.sessions[session_id]
        st.cancelled = False
        st.status = SessionStatus.RUNNING
        st.updated_at = utcnow()
        if st.title == "新对话" and user_text.strip():
            st.title = user_text.strip()[:40]
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        st.last_run_id = run_id
        trace_id = f"tr_{uuid.uuid4().hex[:10]}"
        shop = shop_id or st.shop_id or (st.tenant.shop_ids[0] if st.tenant.shop_ids else "")
        st.shop_id = shop
        st.messages.append(ChatMessage(role="user", content=user_text))
        self._on_event = on_event
        self._emit("plan", "正在理解问题并选择工具…")

        hit = self.injection_detector.check(user_text)
        if hit.matched:
            self.audit.append(
                {
                    "type": "PROMPT_INJECTION_BLOCKED",
                    "session_id": session_id,
                    "tenant_id": st.tenant.tenant_id,
                    "user_text": user_text,
                    "trace_id": trace_id,
                    "pattern": hit.pattern,
                }
            )
            # Turn-level failure only — session stays usable
            result = self._error_result(
                st,
                run_id,
                shop,
                trace_id,
                "该请求涉及高危或越权操作，已拒绝并记录审计。",
                ["查看帮助"],
                session_fatal=False,
            )
            st.messages.append(
                ChatMessage(
                    role="assistant",
                    content=result.blocks[0].content or "",
                    blocks=list(result.blocks),
                    run_id=run_id,
                )
            )
            self._persist(st)
            return result

        try:
            result = self._run_turn(st, user_text, shop=shop, run_id=run_id, trace_id=trace_id)
        except PermissionDenied as e:
            result = self._error_result(st, run_id, shop, trace_id, e.message, ["改条件", "查看帮助"])
        except ToolExecutionError as e:
            actions = ["重试", "改条件", "查看帮助"] if e.retryable else ["改条件", "查看帮助"]
            result = self._error_result(st, run_id, shop, trace_id, e.message, actions)
        except TurnBudgetExceeded as e:
            self.audit.append(
                {
                    "type": "TURN_BUDGET_EXCEEDED",
                    "trace_id": trace_id,
                    "tenant_id": st.tenant.tenant_id,
                    "used": e.used,
                    "limit": e.limit,
                }
            )
            result = self._error_result(st, run_id, shop, trace_id, e.message, ["缩小范围", "改条件"])
        except HallucinationDetected as e:
            self.audit.append(
                {
                    "type": "HALLUCINATION",
                    "trace_id": trace_id,
                    "tenant_id": st.tenant.tenant_id,
                    "message": e.message,
                }
            )
            result = self._error_result(
                st, run_id, shop, trace_id, "分析结果未通过数据校验，已拦截可能不准确的数值。", ["重试"]
            )
        except DomainError as e:
            result = self._error_result(st, run_id, shop, trace_id, e.message, ["查看帮助"])

        st.messages.append(
            ChatMessage(
                role="assistant",
                content=" ".join(b.content or b.question or "" for b in result.blocks)[:500],
                blocks=list(result.blocks),
                run_id=run_id,
            )
        )
        st.updated_at = utcnow()
        self._persist(st)
        self._emit("done", "本轮分析完成", status=result.status)
        return result

    def _run_turn(
        self, st: SessionState, user_text: str, *, shop: str, run_id: str, trace_id: str
    ) -> AgentTurnResult:
        specs = self.tools.list_specs()
        structured = self._build_context(st, user_text, shop)
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=build_system_prompt(self.catalog) + "\n\n" + structured.role_rules),
            LLMMessage(
                role="user",
                content=(
                    f"[Task]\n{user_text}\n\n"
                    f"[Evidence]\n{structured.evidence}\n\n"
                    f"[Context]\n{structured.context}\n\n"
                    f"默认店铺 shop_id={shop}；若用户未指定店铺请使用该值。"
                ),
            ),
        ]

        tool_results: list[ToolResult] = []
        clarification: MessageBlock | None = None
        budget = TurnTokenBudget(self.max_turn_tokens)
        budget.ensure(estimate_messages_tokens(messages))

        for _round in range(self.max_tool_rounds):
            if st.cancelled:
                st.status = SessionStatus.CANCELLED
                return AgentTurnResult(
                    session_id=st.session_id,
                    run_id=run_id,
                    status=st.status.value,
                    blocks=[],
                    meta=self._meta(st, shop, trace_id, model=self._model_name()),
                )

            # Reserve room for the next LLM call on current transcript
            budget.ensure(estimate_messages_tokens(messages) // 8 + 200)
            self._emit("llm", f"第{_round + 1}轮模型规划")
            est = estimate_messages_tokens(messages)
            llm_out = self.llm.complete(
                messages,
                tools=specs,
                tool_choice="auto",
                on_delta=lambda chunk: self._emit("token", chunk),
            )
            usage = (llm_out.raw or {}).get("usage") or {}
            self.ops.record_llm(token_est=int(usage.get("total_tokens") or est))
            budget.add(estimate_text_tokens(llm_out.content))

            if not llm_out.tool_calls:
                self._emit("validate", "正在校验数值是否来自工具结果…")
                blocks = self.block_composer.compose(
                    session_id=st.session_id,
                    content=llm_out.content or "",
                    tool_results=tool_results,
                )
                self.validator.assert_blocks_grounded(blocks, tool_results)
                st.status = SessionStatus.COMPLETED
                self.memory_writer.maybe_write(
                    tenant_id=st.tenant.tenant_id,
                    user_id=st.tenant.user_id,
                    shop_ids=list(st.tenant.shop_ids) or ([shop] if shop else []),
                    user_text=user_text,
                    blocks=blocks,
                    tool_results=tool_results,
                    data_as_of=self.data_as_of,
                    feedback_blocked=st.session_id in self._feedback_wrong_data,
                    cancelled=st.cancelled,
                    writes_blocked=st.writes_blocked,
                )
                if tool_results:
                    self.working.put(st.session_id, ",".join(tr.name for tr in tool_results))
                self.audit.append(
                    {
                        "type": "CONTEXT_SELECT",
                        "trace_id": trace_id,
                        "tenant_id": st.tenant.tenant_id,
                        "kept": structured.select_log.kept,
                        "dropped": structured.select_log.dropped,
                        "reasons": structured.select_log.reasons,
                        "role_rules": structured.role_rules,
                        "token_budget_used": budget.used,
                        "token_budget_limit": budget.max_tokens,
                    }
                )
                return AgentTurnResult(
                    session_id=st.session_id,
                    run_id=run_id,
                    status=st.status.value,
                    blocks=blocks,
                    meta=self._meta(st, shop, trace_id, model=llm_out.model or self._model_name()),
                    tool_traces=[self._trace(tr) for tr in tool_results],
                )

            messages.append(
                LLMMessage(
                    role="assistant",
                    content=llm_out.content,
                    tool_calls=[
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in llm_out.tool_calls
                    ],
                )
            )
            budget.add(estimate_messages_tokens(messages[-1:]))

            for tc in llm_out.tool_calls:
                if tc.name == "ask_clarification":
                    self._emit("tool", "需要向你澄清口径", tool=tc.name)
                    clarification = MessageBlock(
                        type=BlockType.CLARIFICATION.value,
                        question=str(tc.arguments.get("question") or "请补充信息"),
                        options=list(tc.arguments.get("options") or []),
                    )
                    tool_results.append(
                        ToolResult(
                            ok=True,
                            name=tc.name,
                            data=tc.arguments,
                            numeric_facts=[],
                            blocks=[clarification],
                        )
                    )
                    messages.append(
                        LLMMessage(
                            role="tool",
                            tool_call_id=tc.id,
                            name=tc.name,
                            content=json.dumps(
                                {"status": "waiting_user", **tc.arguments}, ensure_ascii=False
                            ),
                        )
                    )
                    continue

                args = dict(tc.arguments)
                if "shop_id" in (self._spec_props(specs, tc.name)) and not args.get("shop_id"):
                    args["shop_id"] = shop

                self._emit("tool", f"调用工具 {tc.name}", tool=tc.name)
                result = self.tools.execute(st.tenant, tc.name, args)
                tool_cost = estimate_tool_result_tokens(result)
                budget.ensure(tool_cost)
                tool_results.append(result)
                tool_msg = LLMMessage(
                    role="tool",
                    tool_call_id=tc.id,
                    name=tc.name,
                    content=json.dumps(
                        {"ok": result.ok, "data": result.data, "error": result.error_message},
                        ensure_ascii=False,
                    ),
                )
                messages.append(tool_msg)
                budget.add(estimate_text_tokens(tool_msg.content))
                if not result.ok:
                    raise ToolExecutionError(
                        result.error_message or "工具执行失败",
                        code=result.error_code or "TOOL_ERROR",
                        retryable=result.error_code in {"RATE_LIMITED", "WAREHOUSE_TIMEOUT"},
                    )

            if clarification:
                st.status = SessionStatus.AWAITING_CLARIFICATION
                return AgentTurnResult(
                    session_id=st.session_id,
                    run_id=run_id,
                    status=st.status.value,
                    blocks=[clarification],
                    meta=self._meta(st, shop, trace_id, model=llm_out.model or self._model_name()),
                    tool_traces=[self._trace(tr) for tr in tool_results],
                )

            messages.append(LLMMessage(role="user", content=FINAL_ANSWER_INSTRUCTION))
            budget.add(estimate_text_tokens(FINAL_ANSWER_INSTRUCTION))

        blocks = self.block_composer.compose(
            session_id=st.session_id,
            content="已汇总工具返回数据。",
            tool_results=tool_results,
        )
        blocks.insert(
            0,
            MessageBlock(
                type=BlockType.WARNING.value,
                content="分析步骤较多已达上限，以下为已获取的数据摘要。",
            ),
        )
        st.status = SessionStatus.COMPLETED
        return AgentTurnResult(
            session_id=st.session_id,
            run_id=run_id,
            status=st.status.value,
            blocks=blocks,
            meta=self._meta(st, shop, trace_id, model=self._model_name()),
            tool_traces=[self._trace(tr) for tr in tool_results],
        )

    def _build_context(self, st: SessionState, user_text: str, shop: str):
        system = [
            ContextPacket(
                content="SYSTEM_RULES_MUST_KEEP: 指标禁止心算；工具结果为准。",
                token_count=20,
                timestamp=utcnow(),
                relevance_score=1.0,
                importance=10.0,
                source_type=SourceType.SYSTEM.value,
                packet_id="sys",
            )
        ]
        recent_tools = self.working.get(st.session_id)
        if recent_tools:
            system.append(
                ContextPacket(
                    content=f"WORKING_MEMORY last_tools={recent_tools}",
                    token_count=12,
                    timestamp=utcnow(),
                    relevance_score=0.8,
                    importance=3.0,
                    source_type=SourceType.SYSTEM.value,
                    packet_id="working",
                )
            )
        sem_hits = self.semantic.search(user_text, limit=3)
        semantic = [
            ContextPacket(
                content=f"{doc.title}: {doc.content}",
                token_count=0,
                timestamp=utcnow(),
                relevance_score=score,
                importance=1.5,
                source_type=SourceType.MEMORY_SEMANTIC.value,
                packet_id=doc.id,
            )
            for score, doc in sem_hits
        ]
        history = [
            ContextPacket(
                content=f"{m.role}: {m.content}",
                token_count=0,
                timestamp=m.created_at,
                relevance_score=0.5,
                importance=1.0,
                source_type=SourceType.HISTORY.value,
                packet_id=f"hist_{i}",
            )
            for i, m in enumerate(st.messages[-6:])
        ]
        return self.context_builder.build(
            task=user_text,
            system=system,
            memory=[],
            semantic=semantic,
            history=history,
            tools=[],
        )

    def _error_result(
        self,
        st: SessionState,
        run_id: str,
        shop: str,
        trace_id: str,
        message: str,
        actions: list[str],
        *,
        session_fatal: bool = False,
    ) -> AgentTurnResult:
        # Turn failures keep the session usable; only session-fatal sets FAILED.
        st.status = SessionStatus.FAILED if session_fatal else SessionStatus.IDLE
        return AgentTurnResult(
            session_id=st.session_id,
            run_id=run_id,
            status="error" if not session_fatal else st.status.value,
            blocks=[MessageBlock(type=BlockType.ERROR.value, content=message, actions=actions)],
            meta=self._meta(st, shop, trace_id, model=self._model_name()),
        )

    def _meta(self, st: SessionState, shop: str, trace_id: str, *, model: str) -> ResponseMeta:
        shops = list(st.tenant.shop_ids) if st.tenant.shop_ids else ([shop] if shop else [])
        channels = list(st.tenant.channels) if st.tenant.channels else ["taobao"]
        return ResponseMeta(
            data_as_of=self.data_as_of,
            shops=shops,
            channels=channels,
            model=model or self._model_name(),
            trace_id=trace_id,
            tenant_id=st.tenant.tenant_id,
        )

    def _model_name(self) -> str:
        getter = getattr(self.llm, "get_model_name", None)
        if callable(getter):
            return str(getter())
        return str(getattr(self.llm, "model_name", "unknown"))

    @staticmethod
    def _trace(tr: ToolResult) -> dict[str, Any]:
        return {"name": tr.name, "ok": tr.ok, "error": tr.error_code, "facts": tr.numeric_facts}

    @staticmethod
    def _spec_props(specs, name: str) -> set[str]:
        for s in specs:
            if s.name == name:
                return set((s.parameters.get("properties") or {}).keys())
        return set()
