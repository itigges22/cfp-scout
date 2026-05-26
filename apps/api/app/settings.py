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
    # LLM — OpenAI-compatible endpoint (see ADR-0001 + plan 10)
    # ------------------------------------------------------------------
    llm_base_url: str = Field(..., description="LLM endpoint base URL.")
    llm_api_key: SecretStr = Field(..., description="LLM API key.")
    llm_chat_model: str = "your-chat-model"
    llm_embedding_model: str = "nomic-embed-text-v1-5"

    # Per-purpose overrides; empty string -> fall back to llm_chat_model.
    llm_extraction_model: str = ""
    llm_narrative_model: str = ""
    llm_agent_model: str = ""

    # Optional separate credentials for the embedding model. Many LLM
    # providers issue per-model keys, so the chat key often can't access
    # the embedding endpoint. When these are set, the LLM client builds
    # a dedicated AsyncOpenAI for embedding calls; when blank, embeddings
    # reuse llm_api_key / llm_base_url.
    llm_embedding_base_url: str = ""
    llm_embedding_api_key: SecretStr | None = None

    llm_dry_run: bool = False
    llm_monthly_budget_usd: float | None = None

    # Maximum concurrent in-flight LLM calls (chat + embedding combined).
    # A bulk rescore enqueues one task per conference; without a cap,
    # APScheduler runs them all in parallel and the burst trips the LLM
    # provider's rate limit (429 Too Many Requests), causing every retry
    # to also 429 (thundering herd). Default 3 is safe under typical RPM
    # quotas; raise via /settings/tunables if you have headroom.
    llm_max_concurrent_calls: int = Field(default=3, ge=1, le=20)

    # ------------------------------------------------------------------
    # Matcher score rescaler
    # ------------------------------------------------------------------
    # rescale_score() maps a raw (properly-normalized) cosine in
    # [floor, ceiling] → [0, 1]. Defaults calibrated from the actual
    # distribution observed on this DB (nomic-embed-text-v1-5, ~10K
    # conference-vs-messaging pairs):
    #
    #   p50 = 0.00    (median pair — totally unrelated)
    #   p90 = 0.14
    #   p95 = 0.22
    #   p99 = 0.37    (strong match)
    #   max = 0.59    (very strong match)
    #
    # Floor 0.10 zeros out the noise floor; ceiling 0.45 saturates at
    # very-strong-match (top 1% of pairs). Mid-range pairs (0.20-0.25)
    # land around 30-40% — a sensible "this is plausible" score.
    #
    # If you swap embedding models (e.g. to OpenAI's text-embedding-3),
    # recalibrate by running:
    #   SELECT percentile_cont(0.5/0.95) WITHIN GROUP (ORDER BY 1 -
    #          (a.embedding <=> b.embedding)) FROM vectors.document_chunks a,
    #          vectors.document_chunks b WHERE a.owner_type='conference'
    #          AND b.owner_type='messaging';
    # and set the floor to the p50 + ceiling to ~the max you've seen.
    matcher_baseline_cosine: float = Field(default=0.10, ge=0.0, le=1.0)
    matcher_ceiling_cosine: float = Field(default=0.45, ge=0.0, le=1.0)

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

    # SME matcher (plan 18) per-dimension weights. Sum must equal 1.0; the
    # validator below enforces. Per-dimension breakdown surfaces in
    # /api/v1/conferences/{id}/smes so users can see why an SME ranked
    # where they did.
    sme_w_topic: float = 0.30
    sme_w_audience: float = 0.25
    sme_w_bio: float = 0.30
    sme_w_location: float = 0.10
    sme_w_past: float = 0.05

    # Label of the "home" team — used purely for UI distinction
    # (an SME whose team field doesn't match this gets tagged
    # ``is_external=True``, which the frontend may surface as a small
    # "(external)" label). Empty string disables the distinction
    # entirely and every SME is treated as internal.
    primary_team_label: str = Field(default="")

    # Stage D — LLM-as-judge reranker.
    # When enabled, the matcher makes one extra LLM call per conference
    # to produce a calibrated 0..1 cross-encoder-style score. This
    # catches relevance the cosine + lexical signals miss (a vLLM
    # meetup that the embedder thinks is "mostly inference" but a
    # human/LLM would see as a perfect organizational fit). Disable
    # to save LLM cost — overall_score re-normalizes across the
    # remaining stages.
    enable_llm_judge: bool = Field(default=True)
    match_w_judge: float = Field(default=0.30, ge=0.0, le=1.0)

    # Stage D enhancements: few-shot calibration + response cache.
    # When enabled, the judge prompt prepends recent approve/reject
    # decisions from ``app.decisions`` as in-context examples, so the
    # judge learns the operator's actual taste over time without any
    # LLM fine-tuning. The cache skips the LLM call entirely when
    # the conference text + pillar context + example set haven't
    # changed since the previous run — typically saves 90%+ of LLM
    # cost + latency on repeat rescores.
    enable_judge_few_shot: bool = Field(default=True)
    enable_judge_cache: bool = Field(default=True)

    # Post-matcher score adjustments — see app/services/matcher/boosts.py.
    # Each one is small (+/- 0.10 max) so the semantic matcher
    # dominates; these just nudge actionable events up and unactionable
    # events down. Toggleable individually for ops calibration.
    enable_cfp_urgency_boost: bool = Field(default=True)
    enable_recency_penalty: bool = Field(default=True)
    enable_series_memory_boost: bool = Field(default=True)

    # SME narrative (plan 19). Hard cap on how many narratives we generate
    # per conference — cost = K LLM calls per conference. K=3 is the
    # plan's default + acceptance criterion.
    sme_narrative_top_k: int = Field(default=3, ge=1, le=10)

    # Multi-SME team recommendations (plan 32). Pure-algorithmic team
    # scoring with no LLM cost. Knobs are env-tunable per plan-spec.
    team_topk_candidates: int = Field(default=10, ge=2, le=30)
    team_w_individual: float = 0.5
    team_w_coverage: float = 0.35
    team_w_redundancy: float = 0.10
    team_w_location: float = 0.05

    decay_enabled: bool = True

    # ------------------------------------------------------------------
    # Discovery (plan 35, PRD §1 + §4): autonomous conference finder
    # ------------------------------------------------------------------
    discovery_enabled: bool = True
    discovery_search_provider: Literal["ddg", "brave", "tavily"] = "ddg"
    discovery_brave_api_key: SecretStr | None = None
    discovery_tavily_api_key: SecretStr | None = None
    discovery_template_prompt: str = Field(
        default=(
            'AI event 2026 "call for papers" OR "call for speakers" OR '
            '"open sponsor" conference summit workshop meetup'
        ),
        description=(
            "Search prompt for /discover. Targets the full event universe "
            "(conferences, summits, workshops, meetups, hackathons, panels) "
            "as long as they have an open CFP, speaker call, or sponsorship "
            "process. Short + specific works better — DDG returns garbage "
            "for long queries. Editable per-run."
        ),
    )
    discovery_max_results_per_run: int = Field(default=20, ge=1, le=100)
    discovery_cron_hour_utc: int = Field(default=6, ge=0, le=23)
    # When discovery crawls a seed URL (an aggregator like aideadlin.es),
    # we follow the outbound conference-looking links one level deep.
    # This cap bounds how many follow-up URLs ANY one seed page can
    # contribute to a single discovery run — keeps the worst case
    # crawl + LLM token bill bounded.
    discovery_max_links_per_seed: int = Field(default=30, ge=0, le=200)

    # Curated seed URLs the orchestrator ALWAYS crawls in addition to
    # whatever the search step returns. Gives Scout a reliable conference
    # signal independent of search-API flakiness. Operators can edit /
    # extend in /settings/tunables.
    discovery_seed_urls: list[str] = Field(
        default_factory=lambda: [
            # Academic / technical conference deadlines
            "https://aideadlin.es/",  # AI deadline tracker (community-maintained)
            "https://www.wikicfp.com/cfp/call?conference=artificial%20intelligence",
            "https://www.wikicfp.com/cfp/call?conference=machine%20learning",
            # CFP marketplaces (academic + industry + meetup)
            "https://papercall.io/cfps",
            "https://sessionize.com/events",
            # Industry conference indexes + meetup hubs
            "https://www.eventbrite.com/d/online/ai-conference/",
            "https://lu.ma/discover",  # Luma — heavy AI meetup / panel coverage
            # Newsletter / blog hubs that surface fresh AI events
            "https://huggingface.co/blog",
        ],
        description=(
            "URLs always crawled by discovery, regardless of the search "
            "step. Aggregators + meetup hubs + CFP marketplaces. Discovery "
            "follows outbound conference-looking links from each one, so "
            "a single seed page can produce dozens of candidate events."
        ),
    )

    # URL substrings whose pages we refuse to crawl during discovery. The
    # LLM extractor can't make a conference row out of a generic Wikipedia
    # article, OpenReview group page, or social-media post — and burning
    # tokens trying wastes budget. Match is case-insensitive substring.
    # AI keyword filter used by the JSON-feed ingestor (developers.events).
    # Events whose name + tags + description don't contain any of these are
    # dropped. Editable from /settings/tunables so the operator can broaden
    # (catch more events) or tighten (reduce noise) without redeploying.
    # Defaults include EN + ES + PT + JA + ZH + KO variants so the LATAM /
    # Asia conference scene isn't silently filtered out.
    discovery_ai_keywords: list[str] = Field(
        default_factory=lambda: [
            # English — core
            "ai", "ml", "machine learning", "machinelearning",
            "deep learning", "deeplearning", "neural", "neural network",
            "data", "datascience", "data science", "data engineering",
            "big data", "data ops", "dataops",
            # English — LLM / GenAI ecosystem
            "llm", "llms", "gpt", "genai", "generative ai", "generative",
            "agent", "agents", "agentic", "rag", "retrieval-augmented",
            "embedding", "embeddings", "vector", "vector db", "vector search",
            "fine-tune", "fine-tuning", "finetune", "finetuning",
            "transformer", "transformers", "diffusion", "synthetic data",
            "prompt", "prompting", "prompt engineering", "context engineering",
            "tokenizer", "tokenization",
            # English — modalities
            "nlp", "natural language", "computer vision", "vision", "speech",
            "asr", "tts", "audio", "video", "multimodal",
            "robotics", "reinforcement", "rl",
            # English — platforms / tooling
            "mlops", "ml ops", "llmops", "ml platform", "model serving",
            "inference", "training", "evaluation", "evals", "benchmark",
            "huggingface", "hugging face", "pytorch", "tensorflow", "jax",
            "openai", "anthropic", "claude", "gemini", "llama", "mistral",
            # English — adjacent
            "ai safety", "alignment", "interpretability", "trust",
            "responsible ai", "ethics", "fairness", "bias",
            "kubeflow", "kserve", "ray", "vllm", "ollama",
            "mlflow", "wandb", "weights & biases",
            # English — generic event-type signal
            "developer", "devops", "platform", "engineering", "cloud",
            "kubernetes", "k8s", "containers",
            # Spanish (LATAM + ES)
            "inteligencia artificial", "aprendizaje automático",
            "aprendizaje automatico", "aprendizaje profundo",
            "ciencia de datos", "datos", "desarrolladores",
            # Portuguese (BR + PT)
            "inteligência artificial", "inteligencia artificial",
            "aprendizagem de máquina", "aprendizado de máquina",
            "aprendizado profundo", "ciência de dados", "ciencia de dados",
            "desenvolvedores",
            # French
            "intelligence artificielle", "apprentissage automatique",
            "apprentissage profond", "science des données",
            "développeurs",
            # German
            "künstliche intelligenz", "kunstliche intelligenz",
            "maschinelles lernen", "datenwissenschaft", "entwickler",
            # Japanese
            "人工知能", "機械学習", "深層学習", "ディープラーニング",
            "データサイエンス", "エーアイ",
            # Chinese (simplified)
            "人工智能", "机器学习", "深度学习", "数据科学", "大模型",
            # Korean
            "인공지능", "머신러닝", "기계학습", "딥러닝", "데이터사이언스",
        ],
        description=(
            "Keywords used to filter the developers.events feed to AI/ML/data "
            "events. Multilingual by default so LATAM and Asia events aren't "
            "silently dropped. Substring match, case-insensitive."
        ),
    )

    discovery_url_blocklist: list[str] = Field(
        default_factory=lambda: [
            "wikipedia.org",
            "openreview.net",
            "twitter.com",
            "x.com/",
            "linkedin.com",
            "youtube.com",
            "youtu.be",
            "facebook.com",
            "reddit.com",
            "/r/",
            "github.com",
            "stackoverflow.com",
            "medium.com",
        ],
        description=(
            "Discovery skips URLs whose strings contain any of these. "
            "Trims junk results from search step before crawling."
        ),
    )

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
                "Provision a real API key from your LLM provider."
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
    def _matcher_weights_sum_to_one(self) -> Settings:
        total = self.match_w_messaging + self.match_w_pillar + self.match_w_sme
        # Allow tiny floating-point drift.
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"MATCH_W_MESSAGING + MATCH_W_PILLAR + MATCH_W_SME must sum to 1.0; got {total}"
            )
        return self

    @model_validator(mode="after")
    def _sme_matcher_weights_sum_to_one(self) -> Settings:
        total = (
            self.sme_w_topic
            + self.sme_w_audience
            + self.sme_w_bio
            + self.sme_w_location
            + self.sme_w_past
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                "SME_W_TOPIC + SME_W_AUDIENCE + SME_W_BIO + SME_W_LOCATION + "
                f"SME_W_PAST must sum to 1.0; got {total}"
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

    Reads env vars, then merges runtime overrides from
    ``app.services.settings_overrides`` (populated at startup from
    ``app.app_setting_overrides``). Cached; call ``cache_clear()`` after
    mutating overrides so the next read returns the new value.
    """
    # Local import to avoid an import cycle (settings_overrides imports
    # from `app.db.models.ops` which transitively pulls in this module).
    from app.services import settings_overrides

    overrides = settings_overrides.current()
    if overrides:
        return Settings(**overrides)  # type: ignore[arg-type]
    return Settings()  # type: ignore[call-arg]
