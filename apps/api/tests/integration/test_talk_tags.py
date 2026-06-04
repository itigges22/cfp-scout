"""Phase 1 API integration tests for /api/v1/talk-tags."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_tag(async_client: AsyncClient, clean_db) -> None:
    resp = await async_client.post(
        "/api/v1/talk-tags",
        json={"name": "cloud-native", "color": "#4F46E5"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "cloud-native"
    assert body["color"] == "#4F46E5"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_tag_duplicate_409(async_client: AsyncClient, clean_db) -> None:
    await async_client.post("/api/v1/talk-tags", json={"name": "dup-tag"})
    resp = await async_client.post("/api/v1/talk-tags", json={"name": "dup-tag"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_tags(async_client: AsyncClient, clean_db) -> None:
    await async_client.post("/api/v1/talk-tags", json={"name": "alpha"})
    await async_client.post("/api/v1/talk-tags", json={"name": "beta"})

    resp = await async_client.get("/api/v1/talk-tags")
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    assert "alpha" in names
    assert "beta" in names


@pytest.mark.asyncio
async def test_update_tag(async_client: AsyncClient, clean_db) -> None:
    create_resp = await async_client.post("/api/v1/talk-tags", json={"name": "old-name"})
    tag_id = create_resp.json()["id"]

    resp = await async_client.put(
        f"/api/v1/talk-tags/{tag_id}",
        json={"name": "new-name", "color": "#FF0000"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "new-name"
    assert body["color"] == "#FF0000"


@pytest.mark.asyncio
async def test_delete_tag_no_assignments(async_client: AsyncClient, clean_db) -> None:
    create_resp = await async_client.post("/api/v1/talk-tags", json={"name": "to-delete"})
    tag_id = create_resp.json()["id"]

    resp = await async_client.delete(f"/api/v1/talk-tags/{tag_id}")
    assert resp.status_code == 204

    # Verify gone
    list_resp = await async_client.get("/api/v1/talk-tags")
    names = [t["name"] for t in list_resp.json()]
    assert "to-delete" not in names


@pytest.mark.asyncio
async def test_delete_tag_cascades_assignments(
    async_client: AsyncClient, clean_db, test_engine
) -> None:
    """Deleting a tag removes its assignments."""
    from sqlalchemy import text

    # Create tag + talk
    tag_resp = await async_client.post("/api/v1/talk-tags", json={"name": "cascade-tag"})
    tag_id = tag_resp.json()["id"]

    talk_resp = await async_client.post("/api/v1/talks", json={"title": "Tagged Talk"})
    talk_id = talk_resp.json()["id"]

    # Insert assignment directly (no assignment endpoint in scope yet)
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app.talk_tag_assignments (talk_id, tag_id) "
                "VALUES (:tid, :tagid)"
            ),
            {"tid": talk_id, "tagid": tag_id},
        )

    # Delete the tag
    del_resp = await async_client.delete(f"/api/v1/talk-tags/{tag_id}")
    assert del_resp.status_code == 204

    # Verify assignment cascaded
    async with test_engine.begin() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM app.talk_tag_assignments WHERE talk_id = :tid"
                ),
                {"tid": talk_id},
            )
        ).scalar_one()
    assert count == 0
