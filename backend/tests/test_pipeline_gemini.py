from __future__ import annotations

import json
from pathlib import Path


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

