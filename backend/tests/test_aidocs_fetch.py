"""How a document is fetched, and which credential does it.

No network. ``_pull_over_http`` is exercised against a stubbed ``_api`` so the two
calls, the version selection and the error messages are all testable without a token.

The regression these guard: the hosted backend answered ``api 401 unauthorized`` for
every document because the CLI path silently inherits a developer's Google session,
and a container has no such session. The fix is a service-account token over HTTP; the
tests below pin which path runs when, and that the failure says what to do.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DEV_AUTH_EMAIL", "tester@razorpay.com")
os.environ["DATABASE_URL"] = "sqlite://"

from app import aidocs  # noqa: E402
from app.config import settings  # noqa: E402

DOC = "doc_jeuvvz7fhmvwqott"

HTML = """<html><title>A spec</title><body>
<h2>1. Problem</h2><p>Traffic arrives too early.</p>
<h2>2. Proposal</h2><p>Check dependencies first.</p>
</body></html>"""


class _Response:
    def __init__(self, payload=None, text=""):
        self._payload, self.text = payload, text

    def json(self):
        return self._payload


@pytest.fixture
def with_token(monkeypatch):
    monkeypatch.setattr(settings, "aidocs_token", "aidocs_test_key")
    monkeypatch.setattr(settings, "aidocs_server", "https://aidocs.example.com")


def _stub_api(monkeypatch, versions, html=HTML, calls=None):
    def fake(path, *, token):
        if calls is not None:
            calls.append((path, token))
        if path.endswith("/versions"):
            return _Response(payload=versions)
        return _Response(text=html)

    monkeypatch.setattr(aidocs, "_api", fake)


# ------------------------------------------------------------------- path selection


def test_a_token_means_http_not_the_cli(monkeypatch, with_token) -> None:
    calls: list[tuple[str, str]] = []
    _stub_api(monkeypatch, [{"id": "ver_1", "number": 1, "sha256": "abc"}], calls=calls)
    monkeypatch.setattr(
        aidocs, "_pull_over_cli", lambda _: pytest.fail("CLI must not run when a token is set")
    )

    doc = aidocs.fetch_doc(DOC)

    assert [p for p, _ in calls] == [
        f"/documents/{DOC}/versions",
        f"/documents/{DOC}/versions/ver_1/html",
    ]
    assert {t for _, t in calls} == {"aidocs_test_key"}
    assert doc.version_id == "ver_1"
    assert doc.source_sha256 == "abc"


def test_no_token_falls_back_to_the_cli(monkeypatch) -> None:
    monkeypatch.setattr(settings, "aidocs_token", "")
    monkeypatch.setattr(aidocs, "_pull_over_http", lambda *a, **k: pytest.fail("must not use HTTP"))
    monkeypatch.setattr(aidocs, "_pull_over_cli", lambda _: aidocs.PulledDoc(html=HTML))

    doc = aidocs.fetch_doc(DOC)
    # The CLI cannot report either, which is the cost of the convenient local path.
    assert doc.version_id is None and doc.source_sha256 is None
    assert len(doc.sections) == 2


def test_the_cli_fallback_says_what_to_do_when_it_cannot_run(monkeypatch) -> None:
    monkeypatch.setattr(settings, "aidocs_token", "")
    monkeypatch.setattr(aidocs.shutil, "which", lambda _: None)

    with pytest.raises(aidocs.AidocsUnavailable, match="AIDOCS_TOKEN"):
        aidocs.fetch_doc(DOC)


# --------------------------------------------------------------- version selection


def test_the_highest_numbered_version_wins(monkeypatch, with_token) -> None:
    """Not list order — this RFC's /versions came back oldest-first."""
    calls: list[tuple[str, str]] = []
    _stub_api(
        monkeypatch,
        [
            {"id": "ver_old", "number": 1, "sha256": "a"},
            {"id": "ver_new", "number": 4, "sha256": "d"},
            {"id": "ver_mid", "number": 2, "sha256": "b"},
        ],
        calls=calls,
    )
    doc = aidocs.fetch_doc(DOC)
    assert doc.version_id == "ver_new"
    assert doc.source_sha256 == "d"
    assert calls[1][0].endswith("/versions/ver_new/html")


def test_an_items_wrapper_is_accepted_too(monkeypatch, with_token) -> None:
    _stub_api(monkeypatch, {"items": [{"id": "ver_1", "number": 1, "sha256": "x"}]})
    assert aidocs.fetch_doc(DOC).version_id == "ver_1"


def test_a_document_with_no_versions_is_reported(monkeypatch, with_token) -> None:
    _stub_api(monkeypatch, [])
    with pytest.raises(aidocs.AidocsUnavailable, match="no versions"):
        aidocs.fetch_doc(DOC)


def test_empty_html_is_reported(monkeypatch, with_token) -> None:
    _stub_api(monkeypatch, [{"id": "ver_1", "number": 1}], html="   ")
    with pytest.raises(aidocs.AidocsUnavailable, match="is empty"):
        aidocs.fetch_doc(DOC)


# ------------------------------------------------------------------- error messages
# Each of these was hit for real while diagnosing the hosted backend, so each says
# what to do rather than echoing a status code.


@pytest.mark.parametrize(
    ("status", "expect"),
    [
        (401, "service-account key"),
        (403, "not allowed to read"),
        (404, "no such document"),
        (500, "HTTP 500"),
    ],
)
def test_http_errors_explain_themselves(monkeypatch, with_token, status, expect) -> None:
    class Resp:
        status_code = status

    monkeypatch.setattr(aidocs.httpx, "get", lambda *a, **k: Resp())
    with pytest.raises(aidocs.AidocsUnavailable, match=expect):
        aidocs._api(f"/documents/{DOC}", token="t")


def test_a_transport_failure_is_not_a_traceback(monkeypatch, with_token) -> None:
    def boom(*a, **k):
        raise aidocs.httpx.ConnectError("no route to host")

    monkeypatch.setattr(aidocs.httpx, "get", boom)
    with pytest.raises(aidocs.AidocsUnavailable, match="no route to host"):
        aidocs._api("/documents/x", token="t")


def test_a_malformed_doc_id_never_reaches_the_network(monkeypatch, with_token) -> None:
    monkeypatch.setattr(aidocs, "_api", lambda *a, **k: pytest.fail("must not call the API"))
    with pytest.raises(aidocs.AidocsUnavailable, match="not a valid aidocs document id"):
        aidocs.fetch_doc("../../etc/passwd")


# ------------------------------------------------------------------------ plumbing


def test_the_url_is_built_from_the_configured_server(monkeypatch, with_token) -> None:
    seen: dict = {}

    class Resp:
        status_code = 200

    def fake_get(url, **kwargs):
        seen["url"], seen["headers"] = url, kwargs.get("headers", {})
        return Resp()

    monkeypatch.setattr(aidocs.httpx, "get", fake_get)
    aidocs._api("/documents/abc", token="tok_123")

    assert seen["url"] == "https://aidocs.example.com/v1/documents/abc"
    assert seen["headers"]["Authorization"] == "Bearer tok_123"


def test_a_trailing_slash_on_the_server_does_not_double_up(monkeypatch, with_token) -> None:
    monkeypatch.setattr(settings, "aidocs_server", "https://aidocs.example.com/")
    seen: dict = {}

    class Resp:
        status_code = 200

    monkeypatch.setattr(aidocs.httpx, "get", lambda url, **k: (seen.update(url=url), Resp())[1])
    aidocs._api("/documents/abc", token="t")
    assert seen["url"] == "https://aidocs.example.com/v1/documents/abc"


# ------------------------------------------------- reporting the credential we have
# The point of these: a deployment that cannot read documents should say so on
# /health, not force someone to submit a doomed job and read the error.


def test_a_token_reports_ready(monkeypatch, with_token) -> None:
    s = aidocs.credential_status()
    assert (s["mode"], s["ready"]) == ("service_account", "yes")
    assert "aidocs.example.com" in s["detail"]


def test_no_token_but_a_cli_reports_probably(monkeypatch) -> None:
    monkeypatch.setattr(settings, "aidocs_token", "")
    monkeypatch.setattr(aidocs.shutil, "which", lambda _: "/usr/local/bin/aidocs")
    s = aidocs.credential_status()
    assert (s["mode"], s["ready"]) == ("cli", "probably")
    assert "container" in s["detail"]


def test_neither_reports_not_ready_and_says_what_to_do(monkeypatch) -> None:
    """This is exactly the hosted backend's state, and what it should have told us."""
    monkeypatch.setattr(settings, "aidocs_token", "")
    monkeypatch.setattr(aidocs.shutil, "which", lambda _: None)
    s = aidocs.credential_status()
    assert (s["mode"], s["ready"]) == ("none", "no")
    assert "AIDOCS_TOKEN" in s["detail"] and "sa key create" in s["detail"]


def test_the_status_never_contains_the_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "aidocs_token", "aidocs_supersecretvalue")
    assert "supersecretvalue" not in repr(aidocs.credential_status())
