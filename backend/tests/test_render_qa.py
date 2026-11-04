"""Tests for the post-render QA pass.

Needs ffmpeg, and skips cleanly without it. The fixtures are synthesised rather than
rendered, so these run in a couple of seconds.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.render import qa

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _make(path: Path, *, seconds: float, colour: str, tone: str) -> Path:
    """A tiny MP4. ``tone`` is a lavfi audio source — `anullsrc` for silence, `sine`
    for something with a measurable level."""
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={colour}:s=320x568:r=30",
            "-f", "lavfi", "-i", tone,
            "-t", str(seconds),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        check=True, capture_output=True,
    )
    return path


def test_a_black_silent_render_is_reported(tmp_path: Path):
    """The failure the pipeline cannot otherwise see: ffmpeg exits 0, the job is
    marked published, and the post is a black rectangle with no sound."""
    broken = _make(tmp_path / "broken.mp4", seconds=8, colour="black", tone="anullsrc=r=48000:cl=mono")
    findings = qa.inspect(broken, expected_ms=8000)

    assert any("black frames" in f for f in findings), findings
    assert any("silence" in f for f in findings), findings
    assert any("static" in f for f in findings), findings


def test_a_length_mismatch_is_reported(tmp_path: Path):
    """Picture and voice disagreeing is the desync the whole timing contract exists
    to prevent, so it is worth catching in the artifact too."""
    clip = _make(tmp_path / "short.mp4", seconds=4, colour="black", tone="anullsrc=r=48000:cl=mono")
    findings = qa.inspect(clip, expected_ms=30000)
    assert any("picture and voice disagree" in f for f in findings), findings


def test_silence_is_never_amplified(tmp_path: Path):
    """loudnorm on a silent track would chase the target by boosting the noise floor.
    ffmpeg reports -inf for true digital silence, which must not compare as 'quiet'."""
    silent = _make(tmp_path / "silent.mp4", seconds=4, colour="blue", tone="anullsrc=r=48000:cl=mono")
    assert qa.normalize_loudness(silent) is False


def test_a_quiet_reel_is_brought_to_target(tmp_path: Path):
    """The defect this catches in practice: the sample reel measured -22.5 LUFS, which
    is 6.5 LU under target — quiet enough that a viewer reaches for the volume."""
    quiet = _make(
        tmp_path / "quiet.mp4", seconds=6, colour="blue",
        tone="sine=frequency=220:sample_rate=48000",
    )
    # A bare sine is far louder than -16; knock it down so the fixture starts quiet.
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(quiet), "-af", "volume=-24dB",
         "-c:v", "copy", "-c:a", "aac", str(tmp_path / "q2.mp4")],
        check=True, capture_output=True,
    )
    target = tmp_path / "q2.mp4"

    before = qa.measure(target)
    assert before is not None and before.integrated < qa.TARGET_LUFS - qa.LOUDNESS_TOLERANCE_LU

    assert qa.normalize_loudness(target) is True

    after = qa.measure(target)
    assert after is not None
    assert abs(after.integrated - qa.TARGET_LUFS) <= qa.LOUDNESS_TOLERANCE_LU
    # A 0 dBTP master clips on decoders that generate intersample peaks.
    assert after.true_peak <= qa.TARGET_TRUE_PEAK + 0.5


def test_audio_already_on_target_is_left_alone(tmp_path: Path):
    """loudnorm is not a no-op on audio that needs no change — it still re-encodes."""
    clip = _make(
        tmp_path / "ok.mp4", seconds=6, colour="blue",
        tone="sine=frequency=220:sample_rate=48000",
    )
    qa.normalize_loudness(clip)  # first pass brings it to target
    assert qa.normalize_loudness(clip) is False  # second pass declines
