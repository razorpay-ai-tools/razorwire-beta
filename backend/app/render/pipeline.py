"""Render orchestration: internal storyboard -> MP4.

Split into a voice step and a render step so the job can surface the ``voicing`` and
``rendering`` states separately in the UI. The storyboard's ``durationMs`` fields are
filled in from the measured audio here, so the stored storyboard (which the feed's
browser reel and the Spec view read) is timed to the same audio as the MP4.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ..storyboard import Storyboard
from . import capture, compose, html, tts
from .errors import RenderUnavailable

__all__ = ["RenderResult", "RenderUnavailable", "voice_storyboard", "render_from_voiced", "render_video"]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderResult:
    mp4_path: Path
    duration_ms: int
    scene_durations: list[int]


def voice_storyboard(sb: Storyboard, work_dir: Path) -> list[tts.Voiced]:
    """Speak every scene and stamp the measured ``durationMs`` back onto the model."""
    narrations = [scene.narration for scene in sb.scenes]
    voiced = tts.voice_scenes(narrations, work_dir)
    for scene, spoken in zip(sb.scenes, voiced):
        scene.duration_ms = spoken.duration_ms
    return voiced


def _scene_clip(scene) -> Path | None:
    """The footage file for this scene's broll mood, if the library has one."""
    mood = getattr(getattr(getattr(scene, "broll", None), "mood", None), "value", None)
    if not mood:
        return None
    clip = Path(settings.broll_dir) / f"{mood}.mp4"
    return clip if clip.is_file() else None


def render_from_voiced(sb: Storyboard, voiced: list[tts.Voiced], work_dir: Path) -> RenderResult:
    """Capture each scene and compose the MP4. Assumes ``voice_storyboard`` has run."""
    width, height, fps = settings.render_width, settings.render_height, settings.render_fps

    clips = [_scene_clip(scene) for scene in sb.scenes]
    htmls = [
        html.scene_html(scene, width=width, height=height, over_footage=clip is not None)
        for scene, clip in zip(sb.scenes, clips)
    ]
    frame_sets = capture.capture_scenes(
        htmls, work_dir, width=width, height=height, keep_alpha=[c is not None for c in clips]
    )

    segments = [
        compose.Segment(pngs=frames, wav=spoken.wav_path, duration_ms=spoken.duration_ms, clip=clip)
        for spoken, frames, clip in zip(voiced, frame_sets, clips)
    ]
    mp4 = compose.compose(
        segments, work_dir / "video.mp4", fps=fps, width=width, height=height
    )
    durations = [spoken.duration_ms for spoken in voiced]
    return RenderResult(mp4_path=mp4, duration_ms=sum(durations), scene_durations=durations)


def render_video(sb: Storyboard, work_dir: Path) -> RenderResult:
    """Voice then render. Convenience for tests and one-shot callers.

    :raises RenderUnavailable: if ffmpeg or Chromium is missing
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    voiced = voice_storyboard(sb, work_dir)
    return render_from_voiced(sb, voiced, work_dir)
