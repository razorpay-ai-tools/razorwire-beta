"""Tests for poster selection and frame-0 baking.

The defect under test is not hypothetical: measured on the sample reel, frame 0 is
luma 5.9 on the composition engine and luma 0 on the ffmpeg engine, because both open
on a fade from black — and `publish` was letting the `<video>` use that frame as its
poster.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.render import poster
from app.storyboard import validate_storyboard

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

_STORYBOARD = {
    "meta": {"title": "Poster Test Reel", "tags": ["test"]},
    "source": {"kind": "topic"},
    "scenes": [
        {"type": "title", "heading": "Hello", "narration": "A title scene narration here."},
        {
            "type": "bullets",
            "heading": "Points",
            "bullets": ["One point", "Two point"],
            "narration": "Two short points to consider here.",
        },
        {
            "type": "diagram",
            "heading": "The flow",
            "mermaid": "graph TD\n  A[Edge] --> B[Store]",
            "narration": "A request enters at Edge and reaches the store.",
        },
        {"type": "outro", "cta": "Read the spec", "narration": "The spec has the detail."},
    ],
}

DURATIONS = [4000, 5000, 6000, 3000]  # 18s total


@pytest.fixture
def sb():
    return validate_storyboard(_STORYBOARD, stage="script")


def test_the_diagram_scene_is_preferred_over_the_title(sb):
    """Every reel's title card looks like every other reel's title card. The diagram
    is the frame that says what THIS post is."""
    times = poster.candidate_times(sb, DURATIONS)
    # diagram scene runs 9s -> 15s, sampled at 75% = 13.5s
    assert times[0] == pytest.approx(13.5, abs=0.01)


def test_the_outro_is_never_a_candidate(sb):
    """An outro is a call to action; it says nothing about the content."""
    times = poster.candidate_times(sb, DURATIONS)
    outro_start = sum(DURATIONS[:3]) / 1000
    assert all(at < outro_start for at in times[:-1]), times


def test_no_candidate_lands_in_the_opening_fade(sb):
    """Both engines fade in from black over the first ~0.4s — the exact frames this
    module exists to stop being the thumbnail."""
    assert all(at >= 0.6 for at in poster.candidate_times(sb, DURATIONS))


def test_an_all_black_reel_yields_no_poster(sb, tmp_path: Path):
    """No frame is usable, so nothing is written and the caller keeps the status quo
    rather than baking a black frame over a black frame."""
    black = tmp_path / "black.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x568:r=30",
         "-t", "18", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(black)],
        check=True, capture_output=True,
    )
    assert poster.choose(black, sb, DURATIONS, tmp_path / "out.jpg") is None
    assert not (tmp_path / "out.jpg").exists()


def test_baking_replaces_frame_zero_and_keeps_everything_else(sb, tmp_path: Path):
    """The contract: same duration, audio intact, frame 0 no longer black."""
    clip = tmp_path / "clip.mp4"
    # Black for the first 2s, then bright — so frame 0 is the bug and a later frame
    # is the fix, in one file.
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x568:r=30:d=2",
            "-f", "lavfi", "-i", "color=c=white:s=320x568:r=30:d=16",
            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:d=18",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip),
        ],
        check=True, capture_output=True,
    )

    def probe(path: Path, entries: str) -> str:
        return subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0", str(path)],
            capture_output=True, text=True,
        ).stdout.strip()

    duration_before = probe(clip, "format=duration")
    assert poster._luma_of_frame_zero(clip) < poster.MIN_LUMA

    jpg = poster.apply(clip, sb, DURATIONS)
    assert jpg is not None and jpg.is_file()

    assert poster._luma_of_frame_zero(clip) >= poster.MIN_LUMA
    assert probe(clip, "format=duration") == duration_before
    assert "audio" in probe(clip, "stream=codec_type")
