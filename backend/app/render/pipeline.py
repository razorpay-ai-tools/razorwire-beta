"""Render orchestration: internal storyboard -> MP4.

Split into a voice step and a render step so the job can surface the ``voicing`` and
``rendering`` states separately in the UI. The storyboard's ``durationMs`` fields are
filled in from the measured audio here, so the stored storyboard (which the feed's
browser reel and the Spec view read) is timed to the same audio as the MP4.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path

from ..config import settings
from ..storyboard import Storyboard
from . import capture, compose, html, qa, tts
from . import poster as poster_mod
from .errors import RenderUnavailable

__all__ = ["RenderResult", "RenderUnavailable", "voice_storyboard", "render_from_voiced", "render_video"]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderResult:
    mp4_path: Path
    duration_ms: int
    scene_durations: list[int]
    #: The chosen still, written beside the MP4 and also baked in as frame 0.
    #: None when no frame was bright enough — see ``render/poster.py``.
    poster_path: Path | None = None


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
    """Render the MP4. Assumes ``voice_storyboard`` has run.

    ``settings.render_engine`` selects the backend. Both produce the same
    ``RenderResult`` from the same measured narration durations; they differ only in
    how the picture is made. See ``render/hyperframes.py`` for why the second exists.

    The composition engine needs Node 22+ on PATH, which a deploy image may not have.
    Rather than make the default conditional on the box, a missing toolchain falls
    back to the ffmpeg path and says so: a reel with plainer motion beats a job that
    fails because Chrome's sibling is not installed. Only ``RenderUnavailable`` — the
    "tooling is absent" error — is caught. A composition that lints or renders badly
    raises ``RuntimeError`` and still fails loudly, because that is our bug and
    silently downgrading it would hide it.
    """
    if settings.render_engine == "hyperframes":
        from . import hyperframes as hf_engine

        try:
            return _finish(sb, hf_engine.render_from_voiced(sb, voiced, work_dir))
        except RenderUnavailable as exc:
            log.warning("composition engine unavailable (%s); falling back to ffmpeg", exc)

    return _finish(sb, _render_with_ffmpeg(sb, voiced, work_dir))


def _render_with_ffmpeg(
    sb: Storyboard, voiced: list[tts.Voiced], work_dir: Path
) -> RenderResult:
    """The original path: Playwright stills joined with ``xfade``."""
    width, height, fps = settings.render_width, settings.render_height, settings.render_fps

    clips = [_scene_clip(scene) for scene in sb.scenes]
    # The first cue is the opening subtitle; the capture step swaps in the rest. A
    # scene whose backend produced no cues falls back to its whole narration.
    htmls = [
        html.scene_html(
            scene,
            width=width,
            height=height,
            over_footage=clip is not None,
            caption=spoken.cues[0].text if spoken.cues else None,
        )
        for scene, clip, spoken in zip(sb.scenes, clips, voiced)
    ]
    frame_sets = capture.capture_scenes(
        htmls,
        work_dir,
        width=width,
        height=height,
        keep_alpha=[c is not None for c in clips],
        cues=[spoken.cues for spoken in voiced],
    )

    segments = [
        compose.Segment(
            pngs=frames.content,
            wav=spoken.wav_path,
            duration_ms=spoken.duration_ms,
            clip=clip,
            captions=frames.captions,
        )
        for spoken, frames, clip in zip(voiced, frame_sets, clips)
    ]
    mp4 = compose.compose(
        segments, work_dir / "video.mp4", fps=fps, width=width, height=height
    )
    durations = [spoken.duration_ms for spoken in voiced]
    return RenderResult(
        mp4_path=mp4, duration_ms=sum(durations), scene_durations=durations
    )


def _finish(sb: Storyboard, result: RenderResult) -> RenderResult:
    """Normalise loudness, choose a poster, and log anything that looks wrong.

    Runs for both engines, because both end with a file nobody has watched. No step
    here can fail the job: a reel that is slightly loud is still a reel, and the
    findings are for whoever reads the job log — see ``render/qa.py`` and
    ``render/poster.py`` for why each check is the one it is.

    Order matters. Loudness re-encodes the audio and poster baking re-encodes the
    video while copying the audio, so normalising first means the levelled track
    survives; doing it the other way round would re-encode the poster's video a second
    time for nothing.
    """
    if not settings.render_qa:
        return result
    try:
        qa.normalize_loudness(result.mp4_path)
        poster = poster_mod.apply(result.mp4_path, sb, result.scene_durations)
        findings = qa.inspect(result.mp4_path, expected_ms=result.duration_ms)
    except Exception as exc:  # a QA pass must never be what loses a finished render
        log.warning("post-render QA did not complete: %s", exc)
        return result
    for finding in findings:
        log.warning("render QA: %s: %s", result.mp4_path.name, finding)
    return replace(result, poster_path=poster)


def render_video(sb: Storyboard, work_dir: Path) -> RenderResult:
    """Voice then render. Convenience for tests and one-shot callers.

    :raises RenderUnavailable: if ffmpeg or Chromium is missing
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    voiced = voice_storyboard(sb, work_dir)
    return render_from_voiced(sb, voiced, work_dir)
