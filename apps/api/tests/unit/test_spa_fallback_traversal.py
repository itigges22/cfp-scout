"""The SPA fallback must never serve a file from outside ``apps/api/static``.

``app/main.py``'s catch-all route resolves a user-supplied path against
STATIC_DIR. Starlette hands the handler a percent-DECODED path, so
``/%2e%2e/%2e%2e/etc/passwd`` arrives as ``../../etc/passwd``. Without the
containment check the handler is an unauthenticated arbitrary-file read —
in the container that includes /proc/self/environ, i.e. every secret in
the process environment.

These cases pin that check.
"""

from __future__ import annotations

import pytest
from app.main import STATIC_DIR, app
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not STATIC_DIR.exists(),
    reason="SPA not built; the fallback route is only registered when static/ exists",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def secret_outside_static(tmp_path_factory) -> str:  # type: ignore[no-untyped-def]
    """Drop a canary next to static/ so traversal has something to find."""
    marker = "SCOUT_TRAVERSAL_CANARY"
    target = STATIC_DIR.parent / "traversal_canary.txt"
    target.write_text(marker)
    yield marker
    target.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/traversal_canary.txt",  # encoded ..
        "/..%2ftraversal_canary.txt",  # encoded /
        "/%2e%2e/%2e%2e/traversal_canary.txt",  # two levels
        "/%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd",  # absolute system file
        "/%2e%2e/%2e%2e/%2e%2e/%2e%2e/proc/self/environ",  # secrets in-container
    ],
)
def test_traversal_never_leaks_files_outside_static(
    client: TestClient, secret_outside_static: str, path: str
) -> None:
    resp = client.get(path)
    body = resp.text
    assert secret_outside_static not in body, f"{path} leaked a file outside static/"
    assert "root:" not in body, f"{path} leaked /etc/passwd"
    assert "LLM_API_KEY" not in body, f"{path} leaked the process environment"


def test_escaped_paths_fall_through_to_the_spa_shell(
    client: TestClient, secret_outside_static: str
) -> None:
    """Escaping the root is indistinguishable from a client-side route."""
    resp = client.get("/%2e%2e/traversal_canary.txt")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()


def test_legitimate_static_file_is_still_served(client: TestClient) -> None:
    resp = client.get("/index.html")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()


def test_client_side_route_still_gets_the_shell(client: TestClient) -> None:
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()


def test_unknown_api_path_still_404s_instead_of_serving_html(client: TestClient) -> None:
    resp = client.get("/api/v1/definitely-not-a-route")
    assert resp.status_code == 404
