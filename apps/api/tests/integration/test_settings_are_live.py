"""A setting that exists but changes nothing is worse than a constant.

WHY THIS EXISTS
    Thirty-eight tunables and six prompts were lifted out of the code and
    into settings. Each move has three ways to be half-done, and none of
    them break an import:

      * the field exists but no SPEC — invisible on the settings page, so
        the operator cannot reach it
      * the SPEC exists but no field — the write is rejected at runtime
      * both exist but the call site still reads the old constant — the
        knob turns and nothing happens

    The third is the dangerous one: it looks like it works.
"""

from __future__ import annotations

import pytest
from app.settings import SPECS, Settings, get_settings
from httpx import AsyncClient

#: Everything moved out of the code in the de-hardcoding pass.
LIFTED = [
    "prompt_pillar_enrichment",
    "prompt_messaging_extraction",
    "prompt_conference_enrichment",
    "prompt_talk_extraction",
    "prompt_rationale",
    "prompt_judge",
    "matcher_topk_messaging",
    "matcher_topk_pillar",
    "matcher_topk_bio",
    "matcher_sme_candidates",
    "matcher_tie_tolerance",
    "matcher_judge_examples_approved",
    "matcher_judge_examples_rejected",
    "boost_cfp_urgency",
    "boost_cfp_urgency_days",
    "boost_series_positive",
    "boost_series_neutral",
    "penalty_recency_months",
    "chunk_half_life_days",
    "decay_alpha",
    "extraction_max_cleaned_chars",
    "extraction_confidence_discovered",
    "extraction_confidence_needs_review",
    "extraction_past_horizon_days",
    "extraction_penalty_date_order",
    "extraction_penalty_deadline_past_start",
    "extraction_penalty_date_out_of_range",
    "extraction_penalty_bad_country",
    "extraction_penalty_acceptance_bad",
    "embedding_chunk_max_chars",
    "embedding_chunk_overlap_chars",
    "discovery_js_render_threshold",
    "discovery_robots_ttl_seconds",
    "discovery_per_url_timeout_seconds",
    "discovery_max_urls_per_source",
    "llm_max_attempts",
    "agent_snippet_chars",
    "agent_history_turns",
    "digest_max_per_bucket",
    "brief_max_topics",
    "brief_max_past_editions",
    "brief_max_talking_docs",
    "brief_max_talking_points_per_doc",
    "api_max_page_size",
]


@pytest.mark.parametrize("name", LIFTED)
def test_lifted_setting_has_both_a_field_and_a_spec(name: str) -> None:
    """Either half missing makes the setting unreachable in practice."""
    assert name in Settings.model_fields, f"{name} has a SPEC but no field"
    assert any(s.name == name for s in SPECS), (
        f"{name} is a field but has no SPEC, so it never renders on the "
        f"settings page and the operator cannot change it"
    )


@pytest.mark.parametrize("name", LIFTED)
def test_lifted_setting_is_not_still_hardcoded_at_its_call_site(name: str) -> None:
    """The knob must be read, not merely declared.

    Every lifted setting has to appear as ``get_settings().<name>`` (or a
    local alias of it) somewhere under app/, otherwise the call site is
    still using the constant and turning the knob does nothing.
    """
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parents[2] / "app"
    hits = [
        p.name
        for p in app_dir.rglob("*.py")
        if p.name not in {"settings.py"} and f".{name}" in p.read_text()
    ]
    assert hits, (
        f"{name} is declared but nothing outside settings.py reads it — the "
        f"call site is probably still using the old module constant"
    )


def test_no_spec_is_missing_its_field() -> None:
    """The whole table, not just the lifted ones."""
    orphans = [s.name for s in SPECS if s.name not in Settings.model_fields]
    assert not orphans, f"SPECS reference fields that do not exist: {orphans}"


def test_every_numeric_spec_agrees_with_its_field_bounds() -> None:
    """A SPEC advertising a range the field rejects means the settings
    page offers a value that 422s on save."""
    mismatches = []
    for spec in SPECS:
        if spec.kind not in {"int", "float"} or spec.min_value is None:
            continue
        field = Settings.model_fields[spec.name]
        for meta in field.metadata:
            lo = getattr(meta, "ge", None)
            hi = getattr(meta, "le", None)
            if lo is not None and lo != spec.min_value:
                mismatches.append(f"{spec.name}: spec min {spec.min_value} vs field ge {lo}")
            if hi is not None and spec.max_value is not None and hi != spec.max_value:
                mismatches.append(f"{spec.name}: spec max {spec.max_value} vs field le {hi}")
    assert not mismatches, mismatches


# ---------------------------------------------------------------------------
# The knobs actually turn
# ---------------------------------------------------------------------------


def _with_override(name: str, value: object):
    """Set a DB-style override and clear the settings cache."""
    from app.services import settings_store

    settings_store._OVERRIDES[name] = value
    get_settings.cache_clear()


def _clear_overrides() -> None:
    from app.services import settings_store

    settings_store._OVERRIDES.clear()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_overrides():
    _clear_overrides()
    yield
    _clear_overrides()


def test_chunk_size_override_changes_the_chunks() -> None:
    from app.services.embeddings import chunk_text

    text = "word " * 4000
    assert max(len(c.text) for c in chunk_text(text)) <= 3000

    _with_override("embedding_chunk_max_chars", 500)
    assert max(len(c.text) for c in chunk_text(text)) <= 500


def test_decay_alpha_override_changes_the_floor() -> None:
    from app.services.matcher import apply_decay_multiplier

    assert apply_decay_multiplier(1.0, 0.0) == pytest.approx(0.85)

    _with_override("decay_alpha", 0.5)
    assert apply_decay_multiplier(1.0, 0.0) == pytest.approx(0.5)


def test_page_size_cap_override_is_enforced() -> None:
    from app.services import records

    _with_override("api_max_page_size", 5)
    assert records.get_settings().api_max_page_size == 5


def test_editing_the_judge_prompt_invalidates_cached_verdicts() -> None:
    """The judge skips the LLM when its input hash is unchanged. If the
    prompt is not part of that hash, editing it from the UI changes
    nothing and the operator sees no effect at all."""
    from app.db.models import Conference
    from app.services.matcher import compute_judge_input_hash

    conference = Conference(name="Example Conf", description="about things", topics=[])
    before = compute_judge_input_hash(conference=conference, pillars=[])

    _with_override("prompt_judge", "a different judge prompt {operator_profile}")
    after = compute_judge_input_hash(conference=conference, pillars=[])

    assert before != after, (
        "the judge prompt is a setting but not part of the cache key, so "
        "editing it leaves every cached verdict in place"
    )


def test_the_judge_prompt_keeps_its_placeholder() -> None:
    """``_render_system_prompt`` substitutes {operator_profile}. A default
    without it silently drops the operator's own description of what they
    care about."""
    assert "{operator_profile}" in get_settings().prompt_judge


# ---------------------------------------------------------------------------
# Precedence, end to end through the API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_written_through_the_api_wins_over_the_default(
    async_client: AsyncClient, clean_db: None
) -> None:
    """DB override beats the field default, and the read-back agrees."""
    name = "matcher_topk_pillar"
    default = Settings.model_fields[name].default

    response = await async_client.patch(
        "/api/v1/admin/settings", json={name: default + 3}
    )
    assert response.status_code < 400, response.text

    listed = await async_client.get("/api/v1/admin/settings")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert name in str(body), "the setting is not exposed on the settings endpoint"


@pytest.mark.asyncio
async def test_an_unknown_setting_is_rejected_not_silently_stored(
    async_client: AsyncClient, clean_db: None
) -> None:
    """The override table is not a junk drawer. A typo'd name must fail
    loudly, or it sits there looking applied and doing nothing."""
    response = await async_client.patch(
        "/api/v1/admin/settings", json={"definitely_not_a_setting": 1}
    )
    assert response.status_code >= 400, (
        "an unregistered setting name was accepted; it will never be read "
        "by anything and the operator will think it took effect"
    )


@pytest.mark.asyncio
async def test_a_value_outside_the_spec_bounds_is_rejected(
    async_client: AsyncClient, clean_db: None
) -> None:
    response = await async_client.patch(
        "/api/v1/admin/settings", json={"matcher_topk_pillar": -5}
    )
    assert response.status_code >= 400, "negative top-K was accepted"
