"""/api/v1/admin/settings — read + tune runtime configuration (P3 UX).

Exposes the runtime-tunable subset of ``app/settings.py`` as a UI-driven
control panel. Each setting carries a kind (`int`/`float`/`bool`/`str`/
`secret`), a domain group (LLM / matcher / SME / team / decay / scraper
/ logging), a current value, and a ``restart_required`` flag that the UI
surfaces as a warning where applicable.

Endpoints:
  * ``GET    /api/v1/admin/settings``     — read all exposed settings
  * ``PATCH  /api/v1/admin/settings``     — write a partial update,
                                             validated against the full
                                             Settings model
  * ``DELETE /api/v1/admin/settings/{name}`` — drop an override
                                                (reverts to env-defined
                                                default)
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.db.session import DbSession
from app.services import settings_overrides
from app.settings import Settings, get_settings

log = structlog.get_logger("scout.api.admin_settings")
router = APIRouter(prefix="/api/v1/admin/settings", tags=["admin.settings"])


SettingKind = Literal["int", "float", "bool", "str", "secret", "list_str"]
SettingGroup = Literal["llm", "matcher", "sme", "team", "decay", "discovery", "scraper", "logging"]


class SettingSpec(BaseModel):
    name: str
    kind: SettingKind
    group: SettingGroup
    label: str
    description: str
    restart_required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    enum_values: list[str] | None = None


# ---------------------------------------------------------------------------
# What we expose. NOT exposed: DB creds, storage path, env, scheduler tz,
# CORS, safety classifier (Phase 2). Those are install-time concerns.
# ---------------------------------------------------------------------------
SPECS: list[SettingSpec] = [
    # LLM ---------------------------------------------------------------
    SettingSpec(
        name="llm_api_key",
        kind="secret",
        group="llm",
        label="LLM API key",
        description="OpenAI-compatible API key. Stored encrypted at rest "
        "is a future feature; today the value lands in plain text in the DB.",
        restart_required=True,
    ),
    SettingSpec(
        name="llm_base_url",
        kind="str",
        group="llm",
        label="LLM base URL",
        description="OpenAI-compatible endpoint (e.g. https://your-llm-host.example/v1).",
        restart_required=True,
    ),
    SettingSpec(
        name="llm_chat_model",
        kind="str",
        group="llm",
        label="Chat model",
        description="Default chat model name. Per-purpose overrides below take precedence.",
        restart_required=True,
    ),
    SettingSpec(
        name="llm_embedding_model",
        kind="str",
        group="llm",
        label="Embedding model",
        description="Embedding model name. Common choices include nomic-embed-text-v1-5 or text-embedding-3-small. Required for the matcher.",
        restart_required=True,
    ),
    SettingSpec(
        name="llm_embedding_api_key",
        kind="secret",
        group="llm",
        label="Embedding API key (optional)",
        description="If the chat key can't access the embedding model (common when providers issue per-model keys), paste a key with embedding access here. Leave blank to reuse the chat key.",
        restart_required=True,
    ),
    SettingSpec(
        name="llm_embedding_base_url",
        kind="str",
        group="llm",
        label="Embedding base URL (optional)",
        description="Override the embedding endpoint URL. Leave blank to use the same base URL as chat.",
        restart_required=True,
    ),
    SettingSpec(
        name="llm_dry_run",
        kind="bool",
        group="llm",
        label="Dry-run mode",
        description="If true, the LLM client returns canned responses and never calls the network. Useful when the key is bad or you want to demo without spending budget.",
    ),
    SettingSpec(
        name="llm_monthly_budget_usd",
        kind="float",
        group="llm",
        label="Monthly budget (USD)",
        description="Soft cap on LLM spend per calendar month. Calls past this point are refused with a 429.",
        min_value=0,
        max_value=10_000,
    ),
    SettingSpec(
        name="llm_max_concurrent_calls",
        kind="int",
        group="llm",
        label="Max concurrent LLM calls",
        description="Process-wide cap on in-flight LLM calls (chat + embedding). Default 3 is safe under typical provider quotas. If you see 429 rate-limit errors in /diagnostics during a bulk rescore or matcher fan-out, lower this; if you have headroom and want faster rescores, raise it.",
        min_value=1,
        max_value=20,
    ),
    # Matcher score rescaler -------------------------------------------
    SettingSpec(
        name="matcher_baseline_cosine",
        kind="float",
        group="matcher",
        label="Baseline cosine (rescaler floor)",
        description="Cosine similarity below this scores 0/100. Default 0.65 — the empirical noise floor for nomic-embed-text-v1-5 on AI-domain text (any two AI texts hit ~0.65 even when unrelated). Lower it if you see legit-looking matches scoring 0; raise it if everything still looks too high.",
        min_value=0.0,
        max_value=1.0,
    ),
    SettingSpec(
        name="matcher_ceiling_cosine",
        kind="float",
        group="matcher",
        label="Ceiling cosine (rescaler top)",
        description="Cosine similarity at or above this scores 100/100. Default 0.92 — a strong match for nomic-embed-text-v1-5. Lower if even your best matches are scoring ~80; raise if too many things hit 100.",
        min_value=0.0,
        max_value=1.0,
    ),
    # Matcher gates -----------------------------------------------------
    SettingSpec(
        name="match_m_gate",
        kind="float",
        group="matcher",
        label="Messaging fit gate",
        description="Stage A threshold. Below this, the conference is marked low_messaging_fit.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="match_p_gate",
        kind="float",
        group="matcher",
        label="Pillar alignment gate",
        description="Stage B threshold. Below this, status flips to needs_review_pillar.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="match_s_gate",
        kind="float",
        group="matcher",
        label="SME match gate",
        description="Stage C threshold. Below this, status flips to needs_sme_review.",
        min_value=0,
        max_value=1,
    ),
    # Matcher weights (must sum to 1.0; validator on Settings enforces it)
    SettingSpec(
        name="match_w_messaging",
        kind="float",
        group="matcher",
        label="Weight: messaging",
        description="Component weight in overall_score. Sum of matcher weights must equal 1.0.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="match_w_pillar",
        kind="float",
        group="matcher",
        label="Weight: pillar",
        description="Component weight in overall_score. Sum of matcher weights must equal 1.0.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="match_w_sme",
        kind="float",
        group="matcher",
        label="Weight: SME",
        description="Component weight in overall_score. Sum of matcher weights must equal 1.0.",
        min_value=0,
        max_value=1,
    ),
    # SME ranker weights (must sum to 1.0) ------------------------------
    SettingSpec(
        name="sme_w_topic",
        kind="float",
        group="sme",
        label="Weight: topic overlap",
        description="Topic-Jaccard contribution to the SME composite. SME weights must sum to 1.0.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="sme_w_audience",
        kind="float",
        group="sme",
        label="Weight: audience overlap",
        description="Audience-Jaccard contribution. SME weights must sum to 1.0.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="sme_w_bio",
        kind="float",
        group="sme",
        label="Weight: bio similarity",
        description="Cosine-similarity contribution. SME weights must sum to 1.0.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="sme_w_location",
        kind="float",
        group="sme",
        label="Weight: location",
        description="Geo-proximity contribution. SME weights must sum to 1.0.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="sme_w_past",
        kind="float",
        group="sme",
        label="Weight: past attendance",
        description="Bonus for SMEs who attended this conference's series before. SME weights must sum to 1.0.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="sme_narrative_top_k",
        kind="int",
        group="sme",
        label="Narrative top-K",
        description="LLM call budget per conference for SME-fit narratives.",
        min_value=1,
        max_value=10,
    ),
    # Team recommendations (plan 32) -----------------------------------
    SettingSpec(
        name="team_topk_candidates",
        kind="int",
        group="team",
        label="Team candidate pool size",
        description="Top-K SMEs to enumerate teams from. Larger K = more combos = slower.",
        min_value=2,
        max_value=30,
    ),
    SettingSpec(
        name="team_w_individual",
        kind="float",
        group="team",
        label="Weight: avg individual fit",
        description="Team composite weight on the mean per-SME score.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="team_w_coverage",
        kind="float",
        group="team",
        label="Weight: coverage breadth",
        description="Team composite weight on the fraction of conference topics covered.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="team_w_redundancy",
        kind="float",
        group="team",
        label="Penalty: topic redundancy",
        description="Subtracted from team composite for overlapping experts.",
        min_value=0,
        max_value=1,
    ),
    SettingSpec(
        name="team_w_location",
        kind="float",
        group="team",
        label="Penalty: location redundancy",
        description="Subtracted from team composite if every pick is in the same city (in-person only).",
        min_value=0,
        max_value=1,
    ),
    # Decay -------------------------------------------------------------
    SettingSpec(
        name="decay_enabled",
        kind="bool",
        group="decay",
        label="Decay enabled",
        description="If false, freshness is stuck at 1.0 and the daily decay cron short-circuits.",
    ),
    # Discovery (plan 35) -----------------------------------------------
    SettingSpec(
        name="discovery_enabled",
        kind="bool",
        group="discovery",
        label="Autonomous discovery enabled",
        description="Master switch for the discovery feature. When off, the cron short-circuits and POST /admin/discovery/run-now refuses.",
    ),
    SettingSpec(
        name="discovery_search_provider",
        kind="str",
        group="discovery",
        label="Search provider",
        description="ddg = DuckDuckGo HTML (no API key). brave / tavily require their respective API keys below.",
        enum_values=["ddg", "brave", "tavily"],
    ),
    SettingSpec(
        name="discovery_brave_api_key",
        kind="secret",
        group="discovery",
        label="Brave Search API key",
        description="Required if provider=brave. Free tier 2000 queries/month at search.brave.com/app/api.",
    ),
    SettingSpec(
        name="discovery_tavily_api_key",
        kind="secret",
        group="discovery",
        label="Tavily API key",
        description="Required if provider=tavily. Free tier 1000 queries/month at tavily.com.",
    ),
    SettingSpec(
        name="discovery_template_prompt",
        kind="str",
        group="discovery",
        label="Default search prompt",
        description="Used by the cron + as the default value on the /discover page. Edit to tune what kinds of conferences Scout finds.",
    ),
    SettingSpec(
        name="discovery_max_results_per_run",
        kind="int",
        group="discovery",
        label="Max results per run",
        description="Cap on URLs fetched from search per discovery run. Bounds the cost of each cron tick.",
        min_value=1,
        max_value=100,
    ),
    SettingSpec(
        name="discovery_cron_hour_utc",
        kind="int",
        group="discovery",
        label="Cron hour (UTC)",
        description="Hour of day (0-23 UTC) the daily discovery cron fires. Change requires api restart.",
        min_value=0,
        max_value=23,
        restart_required=True,
    ),
    SettingSpec(
        name="discovery_seed_urls",
        kind="list_str",
        group="discovery",
        label="Seed URLs (always crawled)",
        description="Aggregator / known-conference URLs that discovery always crawls in addition to search hits. Gives a reliable signal floor when DDG/Brave/Tavily return nothing.",
    ),
    SettingSpec(
        name="discovery_ai_keywords",
        kind="list_str",
        group="discovery",
        label="AI keyword filter (multilingual)",
        description="Events whose name + tags + description don't contain any of these (case-insensitive substring match) are dropped from the developers.events feed. Default ships EN + ES + PT + JA + ZH + KO variants so LATAM and Asia events get through. Widen to catch more, tighten to reduce noise.",
    ),
    SettingSpec(
        name="discovery_url_blocklist",
        kind="list_str",
        group="discovery",
        label="URL blocklist (case-insensitive substrings)",
        description="Discovery skips any URL containing one of these strings. Default cuts known-junk results (wikipedia, openreview, twitter, github, …) before paying for a Crawl4AI fetch + LLM extraction.",
    ),
    SettingSpec(
        name="discovery_max_links_per_seed",
        kind="int",
        group="discovery",
        label="Max followed links per seed page",
        description="When discovery crawls an aggregator (aideadlin.es, papercall.io, …) it follows outbound conference-looking links one level deep. This cap is per-seed — bounds the worst-case crawl + LLM cost of a single discovery run.",
        min_value=0,
        max_value=200,
    ),
    # Scraper -----------------------------------------------------------
    SettingSpec(
        name="scraper_default_politeness_seconds",
        kind="int",
        group="scraper",
        label="Default politeness (seconds)",
        description="Min delay between requests to the same host. Per-source overrides exist.",
        min_value=1,
        max_value=60,
    ),
    SettingSpec(
        name="scraper_user_agent",
        kind="str",
        group="scraper",
        label="User-Agent",
        description="Sent on every outbound scrape. Identify yourself; some hosts block defaults.",
        restart_required=True,
    ),
    # Logging -----------------------------------------------------------
    SettingSpec(
        name="log_level",
        kind="str",
        group="logging",
        label="Log level",
        description="Python logging level. Takes effect on next request after change.",
        enum_values=["DEBUG", "INFO", "WARNING", "ERROR"],
    ),
    SettingSpec(
        name="log_format",
        kind="str",
        group="logging",
        label="Log format",
        description="json (default; for prod log shippers) or console (human-readable).",
        enum_values=["json", "console"],
        restart_required=True,
    ),
]
_BY_NAME: dict[str, SettingSpec] = {s.name: s for s in SPECS}


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
class SettingValue(BaseModel):
    spec: SettingSpec
    value: Any  # masked for secrets
    masked: bool = False
    is_overridden: bool = False
    overridden_at: str | None = None
    actor_label: str | None = None


class SettingsResponse(BaseModel):
    items: list[SettingValue]


def _mask(name: str, raw: Any) -> tuple[Any, bool]:
    """Return (display_value, masked). Show last 4 chars for non-empty
    secrets so users can sanity-check they have the right key without
    leaking it."""
    if not raw:
        return ("", False)
    s = str(raw)
    if len(s) <= 4:
        return ("***", True)
    return (f"***{s[-4:]}", True)


@router.get("", response_model=SettingsResponse)
async def list_settings(db: DbSession) -> SettingsResponse:
    settings = get_settings()
    from sqlalchemy import select as _sel

    from app.db.models.ops import AppSettingOverride

    rows = (await db.execute(_sel(AppSettingOverride))).scalars().all()
    overrides_meta = {r.name: (r.updated_at, r.actor_label) for r in rows}

    items: list[SettingValue] = []
    for spec in SPECS:
        raw_value = getattr(settings, spec.name, None)
        if hasattr(raw_value, "get_secret_value"):
            raw_value = raw_value.get_secret_value()
        if spec.kind == "secret":
            display, masked = _mask(spec.name, raw_value)
        else:
            display, masked = raw_value, False
        meta = overrides_meta.get(spec.name)
        items.append(
            SettingValue(
                spec=spec,
                value=display,
                masked=masked,
                is_overridden=spec.name in overrides_meta,
                overridden_at=meta[0].isoformat() if meta else None,
                actor_label=meta[1] if meta else None,
            )
        )
    return SettingsResponse(items=items)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
class PatchRequest(BaseModel):
    """Partial update. Keys must be in ``SPECS``."""

    model_config = ConfigDict(extra="allow")

    actor_label: str = "admin"


class PatchResponse(BaseModel):
    updated: list[str]
    restart_required_for: list[str]
    items: list[SettingValue]


@router.patch("", response_model=PatchResponse)
async def patch_settings(db: DbSession, payload: PatchRequest) -> PatchResponse:
    """Apply a partial update. Unknown keys → 400. Values that would
    break a Settings validator (e.g. weights not summing to 1.0) → 422.
    """
    raw = payload.model_dump()
    actor_label = str(raw.pop("actor_label", "admin"))[:120]

    unknown = [k for k in raw if k not in _BY_NAME]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown setting names: {sorted(unknown)}",
        )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no settings provided",
        )

    coerced: dict[str, Any] = {}
    for name, value in raw.items():
        coerced[name] = _coerce(_BY_NAME[name], value)

    # Validate the FULL settings shape with the new values applied. This
    # catches Settings-level invariants like "matcher weights must sum to
    # 1.0" that no single PATCH could verify in isolation.
    candidate = {**settings_overrides.current(), **coerced}
    try:
        Settings(**candidate)  # type: ignore[arg-type]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"settings validator rejected the patch: {exc}",
        ) from exc

    # Persist + register each override.
    for name, value in coerced.items():
        await settings_overrides.upsert(
            db,
            name=name,
            value=value,
            actor_label=actor_label,
        )
    await db.commit()
    get_settings.cache_clear()

    restart_keys = [name for name in coerced if _BY_NAME[name].restart_required]
    log.info(
        "admin.settings.patched",
        names=list(coerced),
        actor=actor_label,
        restart_required=restart_keys,
    )

    # Build the response payload via the same shape as GET.
    response = await list_settings(db)
    return PatchResponse(
        updated=list(coerced),
        restart_required_for=restart_keys,
        items=response.items,
    )


@router.delete("/{name}")
async def reset_setting(db: DbSession, name: str) -> dict:
    if name not in _BY_NAME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown setting: {name}",
        )
    deleted = await settings_overrides.remove(db, name=name)
    await db.commit()
    get_settings.cache_clear()
    return {"name": name, "deleted": deleted}


# ---------------------------------------------------------------------------
# Full backup / restore — JSON file with every setting (including secrets)
# so the operator can move installs or recover from a wipe without
# re-pasting API keys and re-tuning 33 knobs.
# ---------------------------------------------------------------------------
class SettingsBackup(BaseModel):
    """The export shape. Includes secret values in plain text.

    Treat the file as sensitive — it contains the LLM API key. Save with
    chmod 600, don't commit to git, don't share in chat.
    """

    scout_version: str = "0.1.0"
    exported_at: str
    warning: str = (
        "Contains secret API keys in plain text. Store with chmod 600, "
        "never commit to git, never share."
    )
    settings: dict[str, Any]


@router.get("/export", response_model=SettingsBackup)
async def export_settings(db: DbSession) -> SettingsBackup:
    """Snapshot every known setting (including secrets) for backup / move.

    The returned JSON is a full restore source: every key in `Settings` that
    has a registered SettingSpec is included with its current effective value
    (env default merged with active override). Secrets are emitted in plain
    text — the export is intended for the operator's local disk, not for
    sharing.
    """
    from datetime import UTC, datetime

    s = get_settings()
    payload: dict[str, Any] = {}
    for spec in SPECS:
        raw = getattr(s, spec.name, None)
        # Unwrap SecretStr so the JSON file is round-trip importable.
        if isinstance(raw, SecretStr):
            payload[spec.name] = raw.get_secret_value()
        else:
            payload[spec.name] = raw
    log.warning(
        "admin.settings.exported",
        n_keys=len(payload),
        includes_secrets=True,
    )
    return SettingsBackup(
        exported_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        settings=payload,
    )


class SettingsImportRequest(BaseModel):
    settings: dict[str, Any]
    actor_label: str = Field(default="import", max_length=120)
    skip_unknown: bool = Field(
        default=True,
        description=(
            "If true, silently skip keys not in the current settings spec "
            "(e.g. a setting renamed since the export). If false, 400 on "
            "unknown keys."
        ),
    )


class SettingsImportResponse(BaseModel):
    imported: list[str]
    skipped: list[str]
    restart_required_for: list[str]


@router.post("/import", response_model=SettingsImportResponse)
async def import_settings(
    db: DbSession,
    payload: SettingsImportRequest,
) -> SettingsImportResponse:
    """Apply a settings backup. Idempotent — re-importing the same file is
    a no-op. Existing overrides for keys not in the import are NOT touched
    (use DELETE /{name} or PATCH to undo individual settings)."""
    incoming = dict(payload.settings or {})
    if not incoming:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="settings payload is empty",
        )

    unknown = [k for k in incoming if k not in _BY_NAME]
    if unknown and not payload.skip_unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown settings: {sorted(unknown)}",
        )

    coerced: dict[str, Any] = {}
    skipped: list[str] = list(unknown)
    for name, value in incoming.items():
        if name not in _BY_NAME:
            continue
        if value is None:
            # Treat null as "leave alone" — different from PATCH's strictness.
            skipped.append(name)
            continue
        coerced[name] = _coerce(_BY_NAME[name], value)

    # Validate the full Settings shape with everything applied. Catches
    # cross-field invariants like "matcher weights must sum to 1.0".
    candidate = {**settings_overrides.current(), **coerced}
    try:
        Settings(**candidate)  # type: ignore[arg-type]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"settings validator rejected the import: {exc}",
        ) from exc

    for name, value in coerced.items():
        await settings_overrides.upsert(
            db, name=name, value=value, actor_label=payload.actor_label
        )
    await db.commit()
    get_settings.cache_clear()

    restart_keys = [
        name for name in coerced if _BY_NAME[name].restart_required
    ]
    log.info(
        "admin.settings.imported",
        imported=list(coerced),
        skipped=skipped,
        actor=payload.actor_label,
        restart_required=restart_keys,
    )
    return SettingsImportResponse(
        imported=sorted(coerced),
        skipped=sorted(set(skipped)),
        restart_required_for=restart_keys,
    )


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------
def _coerce(spec: SettingSpec, raw: Any) -> Any:
    """Convert a JSON body field to the storage shape for the override."""
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{spec.name}: null not allowed (use DELETE to reset)",
        )
    if spec.kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.lower() in ("true", "1", "yes", "on")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{spec.name}: expected boolean",
        )
    if spec.kind == "int":
        try:
            v = int(raw)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{spec.name}: expected integer",
            ) from exc
        _bounds_check(spec, v)
        return v
    if spec.kind == "float":
        try:
            v = float(raw)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{spec.name}: expected number",
            ) from exc
        _bounds_check(spec, v)
        return v
    if spec.kind == "list_str":
        if not isinstance(raw, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{spec.name}: expected list of strings",
            )
        return [str(x) for x in raw]
    # str / secret
    v = str(raw).strip()
    if spec.enum_values is not None and v not in spec.enum_values:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{spec.name}: must be one of {spec.enum_values}",
        )
    return v


def _bounds_check(spec: SettingSpec, value: float) -> None:
    if spec.min_value is not None and value < spec.min_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{spec.name}: {value} < min {spec.min_value}",
        )
    if spec.max_value is not None and value > spec.max_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{spec.name}: {value} > max {spec.max_value}",
        )
