"""Tests for the MP4 render pipeline.

Pure-logic tests (HTML generation, silent TTS) run everywhere. The full fixture ->
MP4 test needs ffmpeg + Playwright's Chromium and skips cleanly when they are absent,
and the publish test uses an in-memory DB and a dummy file so it needs neither.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.render import html, tts
from app.render.errors import RenderUnavailable
from app.render.pipeline import RenderResult
from app.render.publish import publish_render
from app.storyboard import validate_storyboard

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "src/lib/fixtures/otm-rearch.storyboard.json"

_STORYBOARD = {
    "meta": {"title": "Render Test Reel", "tags": ["test"]},
    "source": {"kind": "topic"},
    "scenes": [
        {"type": "title", "heading": "Hello World", "narration": "This is a test of the render pipeline."},
        {
            "type": "bullets",
            "heading": "Two points",
            "bullets": ["First point here", "Second point here"],
            "narration": "Here are two short points to consider.",
        },
        {
            "type": "diagram",
            "heading": "The flow",
            "steps": [
                {"src": "Start", "dst": "Middle", "label": "step one", "say": "It begins at the start and moves to the middle."},
                {"src": "Middle", "dst": "End", "label": "step two", "say": "From the middle it carries on to the end."},
            ],
            "narration": "Start goes to the middle, then to the end.",
        },
        {"type": "outro", "cta": "Read the spec", "narration": "Thanks for watching this test."},
    ],
}


def _sb():
    return validate_storyboard(_STORYBOARD, stage="script")


def _has_playwright() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- html


def test_title_html_carries_heading_and_caption():
    scene = _sb().scenes[0]
    out = html.scene_html(scene, width=1080, height=1920)
    assert "Hello World" in out
    assert "This is a test of the render pipeline." in out  # caption = narration
    assert "1080px" in out and "1920px" in out


def test_diagram_html_embeds_real_mermaid_source():
    scene = _sb().scenes[2]
    out = html.scene_html(scene, width=1080, height=1920)
    assert 'class="mermaid"' in out
    assert "graph TD" in out and "Middle" in out  # the actual source, not an image
    assert "mermaid" in out.lower()


def test_bullets_html_lists_every_bullet():
    scene = _sb().scenes[1]
    out = html.scene_html(scene, width=1080, height=1920)
    assert "First point here" in out
    assert "Second point here" in out


# ---------------------------------------------------------------------------- tts


def test_silent_backend_produces_a_wav_with_a_clamped_duration(tmp_path):
    wav = tmp_path / "a.wav"
    duration = tts.synthesize("a few words to speak", wav, backend="silent")
    assert wav.exists()
    assert duration >= 800  # the schema floor


def test_voice_scenes_writes_one_wav_per_scene(tmp_path):
    voiced = tts.voice_scenes(["first line", "second line"], tmp_path, backend="silent")
    assert len(voiced) == 2
    assert all(v.wav_path.exists() and v.duration_ms >= 800 for v in voiced)


# ------------------------------------------------------------------------ publish


def test_publish_render_creates_a_generated_post_and_links_the_job(tmp_path):
    from app.models import Job, User

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    dummy_mp4 = tmp_path / "video.mp4"
    dummy_mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42")  # any bytes; store copies the file

    with Session(engine) as session:
        user = User(email="t@razorpay.com", name="Tester")
        session.add(user)
        session.commit()
        job = Job(requester_id=user.id, source_kind="topic")
        session.add(job)
        session.commit()

        sb = _sb()
        result = RenderResult(mp4_path=dummy_mp4, duration_ms=4200, scene_durations=[1000, 1200, 1000, 1000])
        post = publish_render(session, job, sb, result)

        # Assert while still bound to the session, or attribute access detaches.
        assert post.kind == "generated"
        assert post.media_url and post.media_url.endswith(".mp4")
        assert post.duration_ms == 4200
        assert post.storyboard is not None
        assert job.post_id == post.id


# -------------------------------------------------------------------- integration


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or not _has_playwright(),
    reason="fixture render needs ffmpeg and Playwright",
)
def test_fixture_renders_to_a_real_mp4(tmp_path):
    from app.render import render_video

    data = json.loads(FIXTURE.read_text())
    sb = validate_storyboard(data, stage="script")
    try:
        result = render_video(sb, tmp_path)
    except RenderUnavailable as exc:
        pytest.skip(f"render tooling unavailable: {exc}")

    assert result.mp4_path.exists()
    assert result.mp4_path.stat().st_size > 10_000
    assert result.duration_ms > 0
    assert len(result.scene_durations) == len(sb.scenes)
