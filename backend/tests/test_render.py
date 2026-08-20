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
            "mermaid": "graph TD\n  A[Start] --> B[Middle]\n  B --> C[End]",
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


# ------------------------------------------------------------------------ compose


def test_scene_transitions_start_where_the_narration_hands_over():
    """The one invariant that keeps the MP4 in sync, asserted without ffmpeg.

    `xfade` overlaps its inputs, so N segments joined with a D-second transition come
    out (N-1)*D shorter than their sum. compose() pays for that by holding every scene
    but the last for an extra D, which makes each transition's offset land exactly on
    the sum of the PRECEDING narration durations — the same instant the concatenated
    audio hands over to that scene. Get the padding wrong and the offsets slide left
    once per join, and every scene's visuals run ahead of its voice.
    """
    import re

    from app.render import compose

    durations = [8.5, 12.15, 11.3, 4.275]
    graph = compose._join_filter(len(durations), durations)

    offsets = [float(value) for value in re.findall(r"xfade=[^;]*?offset=([0-9.]+)", graph)]
    expected = [sum(durations[:index]) for index in range(1, len(durations))]
    assert offsets == pytest.approx(expected, abs=0.001)

    # Drop the padding and this is what you get instead: the drift, accumulating.
    unpadded = [total - (i + 1) * compose.SCENE_XFADE_S for i, total in enumerate(expected)]
    assert offsets != pytest.approx(unpadded, abs=0.001)

    # Audio is concatenated, never cross-faded, so no scene's tail is ramped down.
    assert "acrossfade" not in graph
    assert f"concat=n={len(durations)}:v=0:a=1" in graph


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


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or not _has_playwright(),
    reason="footage compositing needs ffmpeg and Playwright",
)
def test_broll_clip_is_composited_behind_the_scene(tmp_path, monkeypatch):
    """A scene whose mood has a clip in broll_dir renders over that footage."""
    import subprocess

    from app.config import settings
    from app.render import render_video

    broll = tmp_path / "broll"
    broll.mkdir()
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=270x480:d=1", "-r", "24",
         str(broll / "team.mp4")],
        check=True, capture_output=True,
    )
    monkeypatch.setattr(settings, "broll_dir", str(broll))
    monkeypatch.setattr(settings, "render_tts", "silent")

    sb = validate_storyboard(
        {
            "meta": {"title": "Footage test", "tags": ["test"]},
            "source": {"kind": "topic"},
            "scenes": [
                {"type": "title", "heading": "Over footage", "narration": "One scene over footage.",
                 "broll": {"mood": "team"}},
                {"type": "bullets", "heading": "Clip again", "bullets": ["First point", "Second point"],
                 "narration": "Footage behind bullets.", "broll": {"mood": "team"}},
                {"type": "bullets", "heading": "No clip", "bullets": ["Third point", "Fourth point"],
                 "narration": "This mood has no clip.", "broll": {"mood": "city"}},
                {"type": "outro", "cta": "Done", "narration": "And one with no broll at all."},
            ],
        },
        stage="script",
    )
    try:
        result = render_video(sb, tmp_path / "work")
    except RenderUnavailable as exc:
        pytest.skip(f"render tooling unavailable: {exc}")

    assert result.mp4_path.exists()
    assert result.mp4_path.stat().st_size > 10_000


def test_the_package_exports_everything_main_imports():
    """`__all__` promising a name is not the same as exporting it.

    `render_from_voiced` was listed in `pipeline.__all__` but missing from the package's
    own re-export, so `main._run_job` raised `cannot import name` on every generation —
    after the paid model call, and reported to the user as a failed pipeline rather than a
    missing import. Reads the import out of main.py rather than hardcoding a list, so a
    name added there and forgotten here fails immediately.
    """
    import re

    import app.render as render

    source = (Path(__file__).parent.parent / "app" / "main.py").read_text()
    imported = set()
    for match in re.finditer(r"from \.render import ([^\n]+)", source):
        imported.update(name.strip() for name in match.group(1).split(","))

    assert imported, "expected main.py to import from .render"
    missing = sorted(name for name in imported if not hasattr(render, name))
    assert not missing, f"app.render does not export {missing}, which main.py imports"
    assert set(render.__all__) >= imported
