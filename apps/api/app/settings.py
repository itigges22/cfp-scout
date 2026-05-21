"""Application settings, driven by environment variables.

Single source of truth for the runtime configuration. Pydantic refuses to
start the app if a required env var is missing or has the placeholder
``changeme`` value — failing loud beats a confusing 500 later.

See ``.env.example`` at the repo root for the user-facing template and
``docs/ops/database.md`` + ``PLANS/phase-1/07-config-and-secrets.md`` for
the design rationale.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Instances are created via :func:`get_settings`."""

    # ------------------------------------------------------------------
    # General
    # ------------------------------------------------------------------
    env: Literal["dev", "prod"] = Field(default="dev", description="Deployment environment.")

    # ------------------------------------------------------------------
    # Postgres
    # ------------------------------------------------------------------
    # The api's RUNTIME connection — uses the limited `app` role created by
    # infra/postgres/init/02-roles-and-schemas.sql. ALEMBIC, in contrast,
    # builds its own URL from POSTGRES_USER / POSTGRES_PASSWORD below so it
    # can run as the superuser for DDL.
    database_url: str = Field(
        ...,
        description="Async DSN the api uses for queries (postgresql+asyncpg://app:...).",
    )

    # Superuser credentials — Alembic uses these. The api proper never does.
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # ------------------------------------------------------------------
    # LLM API — OpenAI-compatible endpoint (see ADR-0001 + plan 10)
    # ------------------------------------------------------------------
    llm_base_url: str = Field(..., description="LLM endpoint base URL.")
    llm_api_key: SecretStr = Field(..., description="LLM API key.")
    llm_chat_model: str = "llama-scout-17b"
    llm_embedding_model: str = "nomic-embed-text-v1-5"

    # Per-purpose overrides; empty string -> fall back to llm_chat_model.
    llm_extraction_model: str = ""
    llm_narrative_model: str = ""
    llm_agent_model: str = ""

    llm_dry_run: bool = False
    llm_monthly_budget_usd: float | None = None

    # ------------------------------------------------------------------
    # Optional safety classifier (Llama-Guard-3-1B; plan 29)
    # ------------------------------------------------------------------
    safety_classifier_enabled: bool = False
    safety_classifier_model: str = "Llama-Guard-3-1B"

    # ------------------------------------------------------------------
    # Storage (mounted volumes)
    # ------------------------------------------------------------------
    storage_path: str = "/var/lib/scout/storage"

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # ------------------------------------------------------------------
    # Scheduler (plan 13)
    # ------------------------------------------------------------------
    scheduler_timezone: str = "UTC"

    # ------------------------------------------------------------------
    # Scraper (plan 14)
    # ------------------------------------------------------------------
    scraper_user_agent: str = Field(
        ...,
        description="Identifying UA string. Required so source operators can contact us.",
    )
    scraper_default_politeness_seconds: int = 3

    # ------------------------------------------------------------------
    # Matcher tuning (env-only; no UI — see plan 18)
    # ------------------------------------------------------------------
    match_m_gate: float = 0.55  # messaging fit gate (Stage A)
    match_p_gate: float = 0.55  # pillar alignment gate (Stage B)
    match_s_gate: float = 0.50  # SME match gate (Stage C top SME)

    match_w_messaging: float = 0.35  # weight on messaging in overall score
    match_w_pillar: float = 0.35
    match_w_sme: float = 0.30

    decay_enabled: bool = True

    # ------------------------------------------------------------------
    # CORS (only relevant when the Vite dev server runs separately)
    # ------------------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # ------------------------------------------------------------------
    # Config loader behaviour
    # ------------------------------------------------------------------
    model_config = SettingsConfigDict(
        # Reads from .env at the repo root if present (and falls back to
        # os.environ). Compose passes env directly so .env isn't read inside
        # the container in normal operation.
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # tolerate unrecognised vars; we only read what we declare
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("llm_api_key", mode="after")
    @classmethod
    def _reject_placeholder_api_key(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value() == "changeme":
            raise ValueError(
                "LLM_API_KEY is still set to the placeholder 'changeme' in .env. "
                "Provision a real key from your LLM provider dashboard."
            )
        return value

    @field_validator("postgres_password", mode="after")
    @classmethod
    def _reject_placeholder_pg_password(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value() == "changeme":
            raise ValueError(
                "POSTGRES_PASSWORD is the placeholder 'changeme'. Set a real value in .env."
            )
        return value

    @field_validator("llm_base_url", "scraper_user_agent")
    @classmethod
    def _reject_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def _matcher_weights_sum_to_one(self) -> "Settings":
        total = self.match_w_messaging + self.match_w_pillar + self.match_w_sme
        # Allow tiny floating-point drift.
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"MATCH_W_MESSAGING + MATCH_W_PILLAR + MATCH_W_SME must sum to 1.0; got {total}"
            )
        return self

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------
    @property
    def superuser_sync_dsn(self) -> str:
        """Sync DSN built from POSTGRES_* env vars, for Alembic's use only.

        Alembic runs DDL operations as the superuser. The api never touches
        this DSN — it connects via ``database_url`` (which uses the limited
        ``app`` role).
        """
        return (
            f"postgresql+psycopg://"
            f"{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def superuser_async_dsn(self) -> str:
        """Async DSN built from POSTGRES_* env vars. Reserved for tasks that
        need superuser access at runtime (none in Phase 1)."""
        return (
            f"postgresql+asyncpg://"
            f"{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def model_for(self, purpose: str) -> str:
        """Resolve the chat model to use for a given purpose, honouring
        per-purpose overrides from env.

        purpose:
          'extraction' -> LLM_EXTRACTION_MODEL or LLM_CHAT_MODEL
          'narrative'  -> LLM_NARRATIVE_MODEL or LLM_CHAT_MODEL
          'agent'      -> LLM_AGENT_MODEL or LLM_CHAT_MODEL
          (default)    -> LLM_CHAT_MODEL
        """
        overrides = {
            "extraction": self.llm_extraction_model,
            "narrative": self.llm_narrative_model,
            "agent": self.llm_agent_model,
        }
        return overrides.get(purpose) or self.llm_chat_model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """FastAPI dependency for accessing the singleton ``Settings`` instance.

    Cached at module load — re-importing the module in tests with a different
    env requires clearing the cache via ``get_settings.cache_clear()``.
    """
    return Settings()  # type: ignore[call-arg]
