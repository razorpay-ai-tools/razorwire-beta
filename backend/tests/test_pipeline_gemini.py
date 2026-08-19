from __future__ import annotations

import json
from pathlib import Path

import httpx


FIXTURE = Path(__file__).resolve().parents[2] / "src" / "lib" / "fixtures" / "otm-rearch.storyboard.json"


def test_gemini_fallback_generates_valid_storyboard(monkeypatch):
    from app import pipeline
    from app.config import settings

    candidate = json.loads(FIXTURE.read_text())
    candidate.pop("source", None)

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(candidate)}]}}]}

    def post(url, **kwargs):
        assert settings.gemini_model in url
        assert kwargs["params"]["key"] == "gemini-test-key"
        assert kwargs["json"]["generationConfig"]["responseMimeType"] == "application/json"
        return Response()

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-test-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-test-model")
    monkeypatch.setattr(pipeline.httpx, "post", post)

    storyboard = pipeline.run_script_stage(
        kind="aidoc",
        text="A doc about OTM re-architecture",
        doc_id="doc_test",
        doc_title="OTM Rearch",
        doc_url="https://aidocs.razorpay.com/app/d/doc_test",
    )

    assert storyboard.source.doc_id == "doc_test"
    assert storyboard.scenes


def test_gemini_http_error_does_not_leak_api_key(monkeypatch):
    from app import pipeline
    from app.config import settings

    def post(url, **kwargs):
        request = httpx.Request("POST", f"{url}?key=secret-key")
        response = httpx.Response(404, text='{"error":"not found"}', request=request)
        raise_for_status = response.raise_for_status

        class Response:
            text = response.text
            status_code = response.status_code

            def raise_for_status(self) -> None:
                raise_for_status()

        return Response()

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "secret-key")
    monkeypatch.setattr(settings, "gemini_model", "gemini-test-model")
    monkeypatch.setattr(pipeline.httpx, "post", post)

    try:
        pipeline.run_script_stage(
            kind="topic",
            text="Make a short storyboard",
            doc_id=None,
            doc_title=None,
            doc_url=None,
        )
    except RuntimeError as exc:
        message = str(exc)
        cause = exc.__cause__
    else:
        raise AssertionError("expected RuntimeError")

    assert "Gemini request failed with HTTP 404" in message
    assert "secret-key" not in message
    assert "key=" not in message
    assert cause is None
