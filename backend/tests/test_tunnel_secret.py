"""The shared-secret gate that fronts a tunnelled backend.

Worth its own file because every case here is a way the gate fails *open* or fails
*closed wrongly*, and both are invisible until someone is already relying on it:
an unset secret that starts rejecting local traffic, a set secret that lets the
generate endpoint through anyway, a preflight rejected before CORS ever sees it, or
`/media` gated so no video plays.

    cd backend && uv run pytest -q tests/test_tunnel_secret.py
"""

from __future__ import annotations

import pytest

# Environment isolation lives in conftest.py, imported before any test module.

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import init_db  # noqa: E402

SECRET = "test-secret-value"


@pytest.fixture(scope="module")
def client() -> TestClient:
    init_db()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def gated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the gate on for one test. The middleware reads settings per request."""
    monkeypatch.setattr(settings, "tunnel_secret", SECRET)


def test_open_when_no_secret_is_configured(client: TestClient) -> None:
    """The default. A laptop-only run must be completely unaffected."""
    assert settings.tunnel_secret == ""
    assert client.get("/feed").status_code == 200


def test_rejects_a_request_with_no_secret(client: TestClient, gated: None) -> None:
    response = client.get("/feed")
    assert response.status_code == 401
    assert "X-Razorwire-Secret" in response.json()["detail"]


def test_rejects_a_wrong_secret(client: TestClient, gated: None) -> None:
    assert client.get("/feed", headers={"x-razorwire-secret": "nope"}).status_code == 401


def test_accepts_the_right_secret(client: TestClient, gated: None) -> None:
    assert client.get("/feed", headers={"x-razorwire-secret": SECRET}).status_code == 200


def test_generate_is_gated(client: TestClient, gated: None) -> None:
    """The endpoint that costs money is the whole reason the gate exists."""
    response = client.post("/generate", json={"kind": "topic", "input": "a topic long enough"})
    assert response.status_code == 401


def test_health_stays_open(client: TestClient, gated: None) -> None:
    """An uptime monitor should not need the secret."""
    assert client.get("/health").status_code == 200


def test_media_stays_open(client: TestClient, gated: None) -> None:
    """A browser <video src> cannot send a custom header, so gating /media would
    mean no video plays anywhere. 404 is the StaticFiles miss, not a rejection —
    what matters is that it is not 401."""
    assert client.get("/media/nothing-here.mp4").status_code == 404


def test_preflight_is_not_rejected(client: TestClient, gated: None) -> None:
    """This middleware is outermost, so it sees OPTIONS before CORS does. A
    preflight carries no custom headers by definition; rejecting it would break
    every cross-origin call with an opaque CORS error instead of a clean 401."""
    response = client.options(
        "/feed",
        headers={
            "Origin": settings.web_origin.split(",")[0].strip(),
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-razorwire-secret",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
