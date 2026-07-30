"""What wraps every request, after middleware and error handlers merged.

WHY THIS EXISTS
    ``middleware.py`` absorbed ``errors.py``. Both register against the
    app object rather than being called by anything, so a mistake there
    fails silently at import time and only shows up as a missing header
    or a leaked traceback in production.

    Middleware order is the subtle part: RequestID is added LAST so it
    runs FIRST, which is what puts a request id on the log line of a
    failure raised inside the auth middleware. Nothing else asserts that.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_liveness_is_process_only(async_client: AsyncClient) -> None:
    """Liveness must not touch the database.

    If it does, a brief database blip restarts every pod instead of just
    failing readiness — turning a recoverable incident into a rolling
    outage. This passes with no DB fixture at all, which is the point.
    """
    response = await async_client.get("/api/v1/healthz")
    assert response.status_code == 200, response.text


async def test_readiness_reports_dependencies(
    async_client: AsyncClient, clean_db: None
) -> None:
    """Readiness is allowed to check downstreams — that is the difference."""
    response = await async_client.get("/api/v1/readyz")
    assert response.status_code in {200, 503}, response.text
    assert response.headers.get("content-type", "").startswith("application/json")


async def test_every_response_carries_a_request_id(
    async_client: AsyncClient, clean_db: None
) -> None:
    """The id is how an operator connects a user's failure to a log line."""
    response = await async_client.get("/api/v1/healthz")
    header = next(
        (v for k, v in response.headers.items() if "request-id" in k.lower()),
        None,
    )
    assert header, f"no request id header; got {dict(response.headers)}"


async def test_security_headers_are_present(
    async_client: AsyncClient, clean_db: None
) -> None:
    response = await async_client.get("/api/v1/healthz")
    lowered = {k.lower() for k in response.headers}
    assert "x-content-type-options" in lowered, (
        f"SecurityHeaders middleware is not running; got {sorted(lowered)}"
    )


async def test_a_bad_body_is_a_422_with_field_detail_not_a_500(
    async_client: AsyncClient, clean_db: None
) -> None:
    """The validation handler must survive the merge — without it a
    malformed body becomes an unhandled exception."""
    response = await async_client.post(
        "/api/v1/conferences", json={"name": None, "start_date": "not-a-date"}
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert "detail" in body, f"422 without field detail is unusable: {body}"


async def test_an_unknown_field_is_rejected_rather_than_ignored(
    async_client: AsyncClient, clean_db: None
) -> None:
    """StrictBase forbids extras so a typo'd key is a 422, not a silently
    dropped value the caller believes was saved."""
    response = await async_client.post(
        "/api/v1/conferences",
        json={"name": "Typo Conf", "websiet": "https://example.com"},
    )
    assert response.status_code == 422, (
        f"unknown field accepted ({response.status_code}); the caller would "
        f"believe 'websiet' was stored"
    )


async def test_a_malformed_uuid_is_a_422_not_a_500(
    async_client: AsyncClient, clean_db: None
) -> None:
    response = await async_client.get("/api/v1/conferences/not-a-uuid")
    assert response.status_code == 422, response.text


async def test_a_missing_row_is_a_404_with_a_json_body(
    async_client: AsyncClient, clean_db: None
) -> None:
    import uuid

    response = await async_client.get(f"/api/v1/conferences/{uuid.uuid4()}")
    assert response.status_code == 404, response.text
    # RFC 7807 problem+json, not bare application/json — a machine-readable
    # error shape with a type URI, which is the better answer.
    assert "json" in response.headers["content-type"], response.headers["content-type"]


async def test_the_openapi_schema_builds(async_client: AsyncClient) -> None:
    """A response model that no longer resolves after the merge breaks
    schema generation for the whole app, not just its own route."""
    # Served under /api, not at the root — the root is the SPA, and an
    # unknown root path falls back to index.html with a 200, so asserting
    # on the wrong path here passes the status check and fails on decode.
    response = await async_client.get("/api/openapi.json")
    assert response.status_code == 200, response.text[:400]
    assert response.json()["paths"], "schema built but has no paths"
