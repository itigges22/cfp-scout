"""Every served route answers, and no merge shadowed another.

WHY THIS EXISTS
    The routers were merged from 33 modules into 10. Route paths are
    registered by decorator, so a mistake there does not break an import
    and does not break a unit test — the endpoint simply stops existing,
    or worse, a path parameter starts swallowing a sibling and the wrong
    handler answers with a plausible body.

    ``apps/web/e2e/api-contract.spec.ts`` guards the SPA's calls, but it
    needs a running server and a browser. This is the same guarantee at
    the pytest layer: enumerate what the app actually serves and prove
    each one is wired to a handler.

WHAT COUNTS AS PASSING
    Not 200. Most of these need data, auth, or a body we are not
    supplying. What matters is that the request REACHES a handler:
    anything except 404 (route missing), 405 (method missing), and 500
    (handler explodes on a well-formed request).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

#: Placeholder values for path parameters. A syntactically valid but
#: absent id should produce 404-the-row, which is indistinguishable from
#: 404-the-route by status alone — so these tests assert on the route
#: table instead (see test_no_path_is_served_by_two_handlers) and use the
#: status only to catch 405 and 500.
_PARAM_VALUES = {
    "conference_id": str(uuid.uuid4()),
    "sme_id": str(uuid.uuid4()),
    "talk_id": str(uuid.uuid4()),
    "topic_id": str(uuid.uuid4()),
    "audience_id": str(uuid.uuid4()),
    "pillar_id": str(uuid.uuid4()),
    "doc_id": str(uuid.uuid4()),
    "source_id": str(uuid.uuid4()),
    "series_id": str(uuid.uuid4()),
    "job_id": str(uuid.uuid4()),
    "participation_id": str(uuid.uuid4()),
    "notification_id": str(uuid.uuid4()),
    "name": "some_setting",
}


def _concrete(path: str) -> str:
    out = path
    for key, value in _PARAM_VALUES.items():
        out = out.replace("{" + key + "}", value)
    # Anything still templated gets a uuid; better a wrong-typed 422 than
    # a literal "{foo}" segment that cannot match.
    while "{" in out:
        head, _, rest = out.partition("{")
        _, _, tail = rest.partition("}")
        out = head + str(uuid.uuid4()) + tail
    return out


def _routes() -> list[tuple[str, str]]:
    from app.main import app

    spec = app.openapi()
    out: list[tuple[str, str]] = []
    for path, methods in spec["paths"].items():
        for method in methods:
            if method.lower() in {"get", "post", "patch", "put", "delete"}:
                out.append((method.upper(), path))
    return sorted(out)


ROUTES = _routes()


def test_the_route_table_is_not_empty() -> None:
    """A guard on the guard. If the spec came back empty every other test
    in this file would vacuously pass."""
    assert len(ROUTES) > 60, f"only {len(ROUTES)} routes — did router mounting break?"


@pytest.mark.parametrize(("method", "path"), ROUTES, ids=lambda v: str(v))
async def test_route_reaches_a_handler(
    async_client: AsyncClient, method: str, path: str
) -> None:
    """No 404-the-route, no 405, no 500 on a well-formed request.

    Deliberately no ``clean_db``: every path parameter is a random UUID and
    every POST goes out bodyless, so nothing here mutates a row. Truncating
    the whole schema once per route would cost more than the rest of the
    integration suite combined.
    """
    response = await async_client.request(method, _concrete(path))

    assert response.status_code != 405, (
        f"{method} {path} is in the schema but the method is not registered"
    )
    # 503 is a legitimate answer, not a crash: a feature gated off by a
    # setting (discovery_enabled) refuses with a message telling the
    # operator which toggle to flip. That is the handler working.
    assert response.status_code != 500, (
        f"{method} {path} returned an unhandled 500: {response.text[:300]}"
    )
    assert response.status_code < 500 or response.status_code == 503, (
        f"{method} {path} returned {response.status_code}: "
        f"{response.text[:300]}"
    )


def test_no_path_is_served_by_two_handlers() -> None:
    """Registration order is load-bearing and merging routers is exactly
    how you break it.

    ``/conferences/stats`` and ``/conferences/duplicates`` are literal
    paths that must be registered BEFORE ``/conferences/{conference_id}``,
    or the path parameter matches first and both endpoints answer with a
    UUID parse error instead.
    """
    from app.main import app

    seen: dict[tuple[str, str], str] = {}
    duplicates: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in methods:
            key = (method, path)
            name = getattr(route, "name", "?")
            if key in seen:
                duplicates.append(f"{method} {path}: {seen[key]} and {name}")
            seen[key] = name

    assert not duplicates, f"the same path is registered twice: {duplicates}"


@pytest.mark.parametrize(
    "literal",
    [
        # The real registered literals. There is no bare /conferences/stats —
        # asserting on one would "fail" simply because it does not exist.
        "/api/v1/conferences/stats/dashboard",
        "/api/v1/conferences/stats/by-location",
        "/api/v1/conferences/duplicates",
    ],
)
async def test_literal_paths_win_over_the_id_pattern(
    async_client: AsyncClient, literal: str
) -> None:
    """The specific failure the conferences merge could have caused.

    If ``/{conference_id}`` were registered first it would match "stats"
    as an id and fail to parse it as a UUID — a 422 with a uuid_parsing
    error. A real 200 (or any non-422) proves the literal route won.
    """
    response = await async_client.get(literal)

    assert response.status_code != 404, f"{literal} is not registered at all"
    if response.status_code == 422:
        body = response.text
        assert "uuid" not in body.lower(), (
            f"{literal} was swallowed by /{{conference_id}} — registration "
            f"order regressed. Body: {body[:300]}"
        )
