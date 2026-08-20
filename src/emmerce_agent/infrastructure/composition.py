"""Composition root — wire ports to implementations from Settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from emmerce_agent.application.agent.orchestrator import AgentOrchestrator
from emmerce_agent.application.agent.result_validator import ResultValidator
from emmerce_agent.application.ports import LLMPort
from emmerce_agent.domain.context import ContextBuilder, ContextConfig
from emmerce_agent.domain.metrics import build_default_catalog
from emmerce_agent.infrastructure.config.settings import Settings
from emmerce_agent.infrastructure.llm import (
    ModelScopeAdapter,
    OpenAICompatAdapter,
    QwenAdapter,
    StubLLMAdapter,
    ZhipuAdapter,
)
from emmerce_agent.infrastructure.memory.stores import (
    InMemoryEpisodicMemory,
    InMemorySemanticMemory,
    seed_semantic,
)
from emmerce_agent.infrastructure.memory.sqlite_episodic import SqliteEpisodicMemory
from emmerce_agent.infrastructure.tools.export_store import InMemoryExportStore
from emmerce_agent.infrastructure.tools.gateway import FeatureFlags, RateLimiter, ToolGateway
from emmerce_agent.application.ops import OpsCollector
from emmerce_agent.infrastructure.memory.sqlite_sessions import SqliteSessionStore
from emmerce_agent.infrastructure.warehouse.csv_loader import default_dataset_dir, load_demo_csv
from emmerce_agent.infrastructure.warehouse.memory_warehouse import MemoryWarehouse, seed_demo_warehouse


@dataclass
class AppContainer:
    settings: Settings
    orchestrator: AgentOrchestrator
    gateway: ToolGateway
    flags: FeatureFlags
    context_config: ContextConfig
    catalog: object
    exports: InMemoryExportStore
    ops: OpsCollector
    feedback_log: list[dict] = field(default_factory=list)

    # back-compat aliases used by API layer
    @property
    def agent(self) -> AgentOrchestrator:
        return self.orchestrator


def build_llm(settings: Settings) -> LLMPort:
    provider = settings.llm_provider
    if provider == "stub":
        return StubLLMAdapter()

    if not settings.llm_api_key:
        raise RuntimeError(f"EMMERCE_LLM_API_KEY required for provider={provider}")

    if provider == "qwen":
        return QwenAdapter(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
        )
    if provider == "zhipu":
        return ZhipuAdapter(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
        )
    if provider in {"modelscope", "ms"}:
        return ModelScopeAdapter(
            api_key=settings.llm_api_key,
            model=settings.llm_model or "deepseek-ai/DeepSeek-V4-Pro",
            base_url=settings.llm_base_url,
            enable_thinking=settings.llm_enable_thinking,
        )
    if provider in {"openai", "openai_compat", "compatible", "deepseek", "ds"}:
        base = settings.llm_base_url or (
            "https://api.deepseek.com/v1" if provider in {"deepseek", "ds"} else ""
        )
        return OpenAICompatAdapter(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=base,
        )
    raise RuntimeError(
        f"Unknown EMMERCE_LLM_PROVIDER={provider!r}; "
        "use stub|qwen|zhipu|modelscope|openai|deepseek"
    )


def build_container(settings: Settings | None = None) -> AppContainer:
    settings = settings or Settings.from_env()
    catalog = build_default_catalog()
    warehouse = MemoryWarehouse()
    dataset = Path(settings.dataset_dir) if settings.dataset_dir else default_dataset_dir()
    try:
        load_demo_csv(warehouse, dataset)
    except FileNotFoundError:
        seed_demo_warehouse(warehouse)

    ops = OpsCollector()
    session_store = (
        SqliteSessionStore(settings.session_sqlite_path)
        if settings.session_backend == "sqlite"
        else None
    )

    episodic = (
        SqliteEpisodicMemory(settings.sqlite_path)
        if settings.memory_backend == "sqlite"
        else InMemoryEpisodicMemory()
    )
    semantic = InMemorySemanticMemory()
    seed_semantic(semantic)
    exports = InMemoryExportStore(ttl_hours=24)
    flags = FeatureFlags()
    context_config = ContextConfig()

    gateway = ToolGateway(
        catalog=catalog,
        warehouse=warehouse,
        episodic=episodic,
        semantic=semantic,
        exports=exports,
        flags=flags,
        limiter=RateLimiter(max_calls=settings.tool_rate_limit_per_minute),
        data_as_of=settings.data_as_of,
        audit_maxlen=settings.audit_maxlen,
        ops=ops,
    )
    llm = build_llm(settings)
    orchestrator = AgentOrchestrator(
        llm=llm,
        tools=gateway,
        catalog=catalog,
        episodic=episodic,
        semantic=semantic,
        context_builder=ContextBuilder(context_config),
        validator=ResultValidator(strict_text_numbers=settings.strict_text_numbers),
        max_tool_rounds=settings.max_tool_rounds,
        max_turn_tokens=settings.max_turn_tokens,
        data_as_of=settings.data_as_of,
        audit_maxlen=settings.audit_maxlen,
        ops=ops,
        session_store=session_store,
    )
    return AppContainer(
        settings=settings,
        orchestrator=orchestrator,
        gateway=gateway,
        flags=flags,
        context_config=context_config,
        catalog=catalog,
        exports=exports,
        ops=ops,
    )
