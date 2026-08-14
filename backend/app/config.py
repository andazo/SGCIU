from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _normalize_database_url(value: str) -> str:
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+psycopg://", 1)
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    app_env: str
    database_url: str
    cors_origins: tuple[str, ...]
    log_level: str
    llm_provider: str
    openai_api_key: str | None
    openai_model: str
    openai_embedding_model: str
    embedding_dimensions: int
    llm_input_cost_per_million: float
    llm_output_cost_per_million: float
    embedding_cost_per_million: float
    agent_max_steps: int
    tool_transport: str
    similarity_threshold: float
    cluster_time_window_days: int
    admin_api_key: str | None
    require_admin_auth: bool

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    default_origins = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    return Settings(
        app_name=os.getenv("APP_NAME", "SGCIU API"),
        app_env=os.getenv("APP_ENV", "development"),
        database_url=_normalize_database_url(
            os.getenv(
                "DATABASE_URL",
                "postgresql+psycopg://app_user:app_password@localhost:5432/app_db",
            )
        ),
        cors_origins=_as_csv(os.getenv("CORS_ORIGINS"), default_origins),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        llm_provider=os.getenv("LLM_PROVIDER", "openai").lower(),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "1536")),
        llm_input_cost_per_million=float(os.getenv("LLM_INPUT_COST_PER_MILLION", "0")),
        llm_output_cost_per_million=float(os.getenv("LLM_OUTPUT_COST_PER_MILLION", "0")),
        embedding_cost_per_million=float(os.getenv("EMBEDDING_COST_PER_MILLION", "0")),
        agent_max_steps=int(os.getenv("AGENT_MAX_STEPS", "4")),
        tool_transport=os.getenv("TOOL_TRANSPORT", "local").lower(),
        similarity_threshold=float(os.getenv("SIMILARITY_THRESHOLD", "0.78")),
        cluster_time_window_days=int(os.getenv("CLUSTER_TIME_WINDOW_DAYS", "30")),
        admin_api_key=os.getenv("ADMIN_API_KEY"),
        require_admin_auth=_as_bool(os.getenv("REQUIRE_ADMIN_AUTH"), default=False),
    )
