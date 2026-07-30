"""Legacy SME fields stay dead.

This file used to test the SME topic cap and primary_topics sync — the
whole topic-vocabulary system those enforced was removed (migration
20260730_1000; free-text ``expertise`` embedded with the bio replaced
it). What survives is the regression guard for fields that must never
reappear in responses: ``expertise_areas`` (removed Migration J) and now
``primary_topics`` too.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text


async def _insert_audience(test_engine, name: str) -> str:
    aid = str(uuid.uuid4())
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.audience_profiles "
                "(id, name, description, industry, role_seniority, "
                "primary_pain_points, key_messages, is_active) "
                "VALUES (:id, :name, 'test audience', 'Tech', 'Senior', "
                "'{}'::text[], '{}'::text[], true)"
            ),
            {"id": aid, "name": name},
        )
    return aid


def _sme_payload(audience_ids: list[str]) -> dict:
    return {
        "full_name": "Test SME",
        "team": "Platform",
        "audience_focus": audience_ids,
        "location_country": "US",
        "bio": "A" * 200,  # min-length satisfied
    }


@pytest.mark.asyncio
async def test_removed_fields_stay_out_of_responses(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """GET /smes/{id} must include neither expertise_areas nor
    primary_topics — both belong to removed systems."""
    aud_id = await _insert_audience(test_engine, "NoLegacyAud")

    create_resp = await async_client.post("/api/v1/smes", json=_sme_payload([aud_id]))
    assert create_resp.status_code == 201, create_resp.text
    sme_id = create_resp.json()["id"]

    get_resp = await async_client.get(f"/api/v1/smes/{sme_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert "expertise_areas" not in body
    assert "primary_topics" not in body


@pytest.mark.asyncio
async def test_primary_topics_in_payload_is_rejected(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """StrictBase forbids unknown fields, so a client still sending the
    removed primary_topics key gets a 422 instead of silent acceptance."""
    aud_id = await _insert_audience(test_engine, "StrictAud")
    payload = _sme_payload([aud_id])
    payload["primary_topics"] = []

    resp = await async_client.post("/api/v1/smes", json=payload)
    assert resp.status_code == 422
