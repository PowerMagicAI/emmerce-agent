"""Environment-based settings for production deployment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_CORS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
)


def _load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (no python-dotenv dependency). Does not override existing env."""
    candidates = []
    if path is not None:
        candidates.append(path)
    else:
        here = Path(__file__).resolve()
        # settings.py -> config -> infrastructure -> emmerce_agent -> src -> repo root
        candidates.append(here.parents[4] / ".env")
        candidates.append(Path.cwd() / ".env")
    for env_path in candidates:
        if not env_path.is_file():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        break


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "emmerce-agent"
    # stub|qwen|zhipu|modelscope|openai
    llm_provider: str = "stub"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "qwen-plus"
    llm_enable_thinking: bool = False
    warehouse_backend: str = "memory"  # memory|mysql (mysql reserved)
    memory_backend: str = "memory"  # memory|sqlite
    sqlite_path: str = "./data/emmerce_episodic.db"
    dataset_dir: str = ""
    session_backend: str = "memory"  # memory|sqlite
    session_sqlite_path: str = "./data/emmerce_sessions.db"
    data_as_of: str = "2026-08-04T08:00:00+08:00"
    max_tool_rounds: int = 8
    max_turn_tokens: int = 32_000
    audit_maxlen: int = 2000
    tool_rate_limit_per_minute: int = 20
    cors_origins: tuple[str, ...] = _DEFAULT_CORS
    auth_secret: str = "emmerce-dev-change-me"
    auth_ttl_hours: int = 12
    strict_text_numbers: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        _load_dotenv()
        origins = os.getenv("EMMERCE_CORS_ORIGINS", "")
        parsed = tuple(o.strip() for o in origins.split(",") if o.strip())
        thinking = os.getenv("EMMERCE_LLM_ENABLE_THINKING", "0").lower() in {"1", "true", "yes"}
        return cls(
            llm_provider=os.getenv("EMMERCE_LLM_PROVIDER", "stub").lower(),
            llm_api_key=os.getenv("EMMERCE_LLM_API_KEY", ""),
            llm_base_url=os.getenv("EMMERCE_LLM_BASE_URL", ""),
            llm_model=os.getenv("EMMERCE_LLM_MODEL", "qwen-plus"),
            llm_enable_thinking=thinking,
            warehouse_backend=os.getenv("EMMERCE_WAREHOUSE_BACKEND", "memory").lower(),
            memory_backend=os.getenv("EMMERCE_MEMORY_BACKEND", "memory").lower(),
            sqlite_path=os.getenv("EMMERCE_SQLITE_PATH", "./data/emmerce_episodic.db"),
            dataset_dir=os.getenv("EMMERCE_DATASET_DIR", ""),
            session_backend=os.getenv("EMMERCE_SESSION_BACKEND", "memory").lower(),
            session_sqlite_path=os.getenv("EMMERCE_SESSION_SQLITE", "./data/emmerce_sessions.db"),
            data_as_of=os.getenv("EMMERCE_DATA_AS_OF", "2026-08-04T08:00:00+08:00"),
            max_tool_rounds=int(os.getenv("EMMERCE_MAX_TOOL_ROUNDS", "8")),
            max_turn_tokens=int(os.getenv("EMMERCE_MAX_TURN_TOKENS", "32000")),
            audit_maxlen=int(os.getenv("EMMERCE_AUDIT_MAXLEN", "2000")),
            tool_rate_limit_per_minute=int(os.getenv("EMMERCE_TOOL_RPM", "20")),
            cors_origins=parsed or _DEFAULT_CORS,
            auth_secret=os.getenv("EMMERCE_AUTH_SECRET", "emmerce-dev-change-me"),
            auth_ttl_hours=int(os.getenv("EMMERCE_AUTH_TTL_HOURS", "12")),
            strict_text_numbers=os.getenv("EMMERCE_STRICT_TEXT_NUMBERS", "1").lower()
            in {"1", "true", "yes"},
        )
