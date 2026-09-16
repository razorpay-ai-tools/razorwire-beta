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
from ..storyboard import DiagramScene, Storyboard
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
    """Speak every scene and stamp the measured ``durationMs`` back onto the model.

    A diagram scene with steps is voiced hop-by-hop (each ``say`` its own clip) so the
    render can reveal each hop in sync; every other scene is one narration clip.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    voiced: list[tts.Voiced] = []
    for index, scene in enumerate(sb.scenes):
        if isinstance(scene, DiagramScene) and scene.steps:
            wav, total, starts = tts.voice_steps([s.say for s in scene.steps], work_dir, index)
            scene.duration_ms = total
            voiced.append(tts.Voiced(index=index, wav_path=wav, duration_ms=total, beat_starts=starts))
        else:
            wav = work_dir / f"scene{index}.wav"
            duration = tts.synthesize(scene.narration, wav)
            scene.duration_ms = duration
            voiced.append(tts.Voiced(index=index, wav_path=wav, duration_ms=duration))
    return voiced


#: A diagram frame-steps fast (smooth arrow draw); a non-diagram scene only needs enough
#: frames for its subtitle to advance, so it is stepped cheaply.
CAPTION_FPS = 6


def _scene_cues(scene, spoken: tts.Voiced) -> list[tuple[int, str]]:
    """Short, audio-timed subtitle cues for a scene. A diagram's cues are its per-hop
    ``say``s timed within each hop's beat; every other scene's are its narration spread
    across the scene's duration."""
    if isinstance(scene, DiagramScene) and scene.steps and spoken.beat_starts:
        starts = spoken.beat_starts
        cues: list[tuple[int, str]] = []
        for i, step in enumerate(scene.steps):
            end = starts[i + 1] if i + 1 < len(starts) else spoken.duration_ms
            cues.extend(html.caption_cues(step.say, starts[i], max(1, end - starts[i])))
        return cues
    return html.caption_cues(scene.narration, 0, spoken.duration_ms)


def render_from_voiced(sb: Storyboard, voiced: list[tts.Voiced], work_dir: Path) -> RenderResult:
    """Capture each scene and compose the MP4. Assumes ``voice_storyboard`` has run.

    Every scene is frame-stepped so its caption rolls in sync with the voice; diagrams
    step fast for a smooth draw, other scenes at a low caption fps.
    """
    width, height, fps = settings.render_width, settings.render_height, settings.render_fps

    specs = []
    scene_fps: list[int] = []
    for scene, spoken in zip(sb.scenes, voiced):
        reveal = html.is_animated(scene)
        stepped = isinstance(scene, DiagramScene) and bool(scene.steps) and bool(spoken.beat_starts)
        this_fps = fps if reveal else CAPTION_FPS
        scene_fps.append(this_fps)
        specs.append(
            capture.SceneCapture(
                html=html.scene_html(
                    scene,
                    width=width,
                    height=height,
                    duration_ms=spoken.duration_ms,
                    beats=[s.say for s in scene.steps] if stepped else None,
                    beat_starts=spoken.beat_starts if stepped else None,
                    caption_cues=_scene_cues(scene, spoken),
                ),
                animated=True,  # frame-step every scene so the caption advances
                duration_ms=spoken.duration_ms,
                fps=this_fps,
            )
        )
    captured = capture.capture(specs, work_dir, width=width, height=height, fps=fps)

    segments = [
        compose.Segment(
            frames=cap.frames, wav=spoken.wav_path, duration_ms=spoken.duration_ms, capture_fps=sfps
        )
        for cap, spoken, sfps in zip(captured, voiced, scene_fps)
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
