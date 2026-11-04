"""The still a reel shows before anyone presses play.

Every generated post in the feed currently has a black thumbnail, and it is not a
bug in any one engine — it is the default behaviour of both, meeting the default
behaviour of every player:

  * ``publish._create_post`` sets ``thumbnail_url=None`` and lets the ``<video>``
    use its own first frame,
  * the ffmpeg engine opens with ``fade=t=in:st=0:d=0.4`` (``compose.OPEN_FADE_S``),
    so frame 0 is black by construction,
  * the composition engine opens on a plate tweened up from ``opacity: 0``, so frame
    0 is near-black too. Measured on the sample reel: YAVG 5.9 out of 255.

Picking a good frame is only half of it. A bare MP4 has no ``poster`` attribute, and
Slack, Twitter and Discord all regenerate thumbnails server-side and ignore embedded
cover art — so the only thing that reliably controls the idle image everywhere is
frame 0 itself. We therefore both write the JPG (for ``thumbnail_url`` and any
``<video poster>``) and overlay it onto frame 0 of the MP4. At 30 fps the poster is
on screen for 1/30 s before the real opening rolls, which is imperceptible on
playback and is exactly what a thumbnail grabber sees.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .errors import RenderUnavailable

log = logging.getLogger(__name__)

#: Where in a scene to sample. The composition engine spends ``BUILD_FRACTION`` (0.55)
#: of a scene building up; 0.75 is past that in every scene long enough to matter, and
#: still clear of the next scene's entrance.
SETTLE_FRACTION = 0.75

#: Mean luma, 0-255, under which a frame is "black enough to be the bug we are fixing".
#: The sample reel's frame 0 measured 5.9; a real razorwire scene on the darkest mood
#: gradient measures well above 20.
MIN_LUMA = 14.0

#: Scene types worth putting on a thumbnail, best first. A diagram is the most
#: distinctive thing a razorwire reel contains and the clearest signal of what the post
#: is; an outro is a call to action and says nothing about the content.
_PREFERRED = ("diagram", "compare", "bullets", "code", "title")

_TIMEOUT = 180


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    if shutil.which("ffmpeg") is None:
        raise RenderUnavailable("ffmpeg is not installed (brew install ffmpeg)")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)


def _starts(scene_durations: list[int]) -> list[float]:
    out, elapsed = [], 0.0
    for ms in scene_durations:
        out.append(elapsed)
        elapsed += ms / 1000
    return out


def candidate_times(sb: Any, scene_durations: list[int]) -> list[float]:
    """Sample points, best first.

    Ordered by scene type rather than by position: the title card is a legible frame
    but every reel's title card looks like every other one, whereas the architecture
    diagram is the frame that tells someone scrolling what this particular post is.
    """
    if not scene_durations:
        return []
    starts = _starts(scene_durations)
    scenes = list(getattr(sb, "scenes", []))

    ranked: list[tuple[int, float]] = []
    for index, ms in enumerate(scene_durations):
        if index >= len(scenes):
            break
        kind = getattr(scenes[index], "type", None)
        if kind == "outro":
            continue
        rank = _PREFERRED.index(kind) if kind in _PREFERRED else len(_PREFERRED)
        ranked.append((rank, starts[index] + (ms / 1000) * SETTLE_FRACTION))

    ranked.sort(key=lambda pair: pair[0])
    times = [at for _, at in ranked]
    # Last resort: the midpoint of the whole reel. Reached only when every scene is an
    # outro, which the storyboard validator should already prevent.
    total = sum(scene_durations) / 1000
    times.append(total / 2)
    # Never the opening fade, and never past the end.
    return [min(max(at, 0.6), max(total - 0.2, 0.6)) for at in times]


def _luma(image: Path) -> float | None:
    """Mean luma of a still, via ffmpeg's own signalstats. 0-255."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-f", "lavfi",
            "-i", f"movie={image},signalstats",
            "-show_entries", "frame_tags=lavfi.signalstats.YAVG",
            "-of", "csv=p=0",
        ],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    line = result.stdout.strip().splitlines()
    try:
        return float(line[0])
    except (IndexError, ValueError):
        return None


def _luma_of_frame_zero(mp4: Path) -> float:
    """Mean luma of the very first frame — the thing every thumbnail grabber takes.

    Exists so "is the thumbnail black?" is one call rather than an ad-hoc ffmpeg
    pipeline each time somebody wants to check.
    """
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame0.png"
        # Decode the frame out first rather than measuring through lavfi's `movie=`
        # source: that form needs the path escaped for the filter parser, and it
        # silently yields nothing when the path contains a character it dislikes —
        # which reads as "luma unknown", not as "this call is broken".
        result = _run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-frames:v", "1", str(frame)])
        if result.returncode != 0 or not frame.is_file():
            return -1.0
        luma = _luma(frame)
    return -1.0 if luma is None else luma


def extract(mp4: Path, at: float, out_jpg: Path) -> bool:
    """One full-resolution frame at ``at`` seconds."""
    result = _run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(mp4),
         "-frames:v", "1", "-q:v", "2", str(out_jpg)]
    )
    return result.returncode == 0 and out_jpg.is_file() and out_jpg.stat().st_size > 0


def choose(mp4: Path, sb: Any, scene_durations: list[int], out_jpg: Path) -> Path | None:
    """Extract the best candidate frame that is not black.

    The luma check is the point of trying more than one candidate: a scene can be
    mid-transition, or its narration can be so short that even 75% through it is still
    fading in. Rather than reason about which, take the first candidate that is
    actually bright enough to be a thumbnail.
    """
    for at in candidate_times(sb, scene_durations):
        if not extract(mp4, at, out_jpg):
            continue
        luma = _luma(out_jpg)
        if luma is None or luma >= MIN_LUMA:
            log.info("poster from %.2fs (luma %.1f)", at, luma if luma is not None else -1)
            return out_jpg
        log.debug("poster candidate at %.2fs too dark (luma %.1f)", at, luma)
    log.warning("no frame of %s was bright enough for a poster", mp4.name)
    out_jpg.unlink(missing_ok=True)
    return None


def bake(mp4: Path, jpg: Path) -> bool:
    """Replace frame 0's pixels with the poster, leaving all other frames and the
    audio untouched. Same duration, same frame count.

    Re-encodes the video stream — ``-c:v copy`` cannot be used because one frame's
    pixels change. Audio is copied, so the loudness pass upstream is preserved.
    """
    if not jpg.is_file():
        return False
    out = mp4.with_suffix(".poster.mp4")
    result = _run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-i", str(jpg),
            "-filter_complex", "[0:v][1:v]overlay=0:0:enable='eq(n,0)'[v]",
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart",
            str(out),
        ]
    )
    if result.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-6:])
        log.warning("could not bake the poster into %s, leaving it as it was:\n%s", mp4.name, tail)
        out.unlink(missing_ok=True)
        return False
    out.replace(mp4)
    return True


def apply(mp4: Path, sb: Any, scene_durations: list[int]) -> Path | None:
    """Pick a poster, write it beside the MP4, and bake it as frame 0.

    :returns: the JPG, or None if no usable frame was found. Never raises — a reel
        without a chosen poster is the status quo, not a failure.
    """
    jpg = mp4.with_suffix(".jpg")
    try:
        if choose(mp4, sb, scene_durations, jpg) is None:
            return None
        bake(mp4, jpg)
        return jpg
    except Exception as exc:
        log.warning("poster step did not complete for %s: %s", mp4.name, exc)
        return None
