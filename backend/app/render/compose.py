"""Frames + narration -> a single MP4, via ffmpeg.

Each scene is encoded to its own SILENT segment: either one still held for the length
of its narration, or the scene's reveal steps cross-faded into each other so a bullet
or a diagram node appears rather than pops. The segments are then joined with an
``xfade`` transition and the narration wavs concatenated underneath, in one pass.

The join arithmetic is the only subtle part. ``xfade`` OVERLAPS its two inputs, so N
segments joined with a ``D``-second transition come out ``(N-1)*D`` shorter than their
sum — which would drag every scene's visuals ``D`` earlier than its narration, once per
join, and the drift would accumulate. So every segment but the last is encoded ``D``
longer than its narration, holding its final frame: the overlap is then made of that
padding rather than of narration, each scene's visuals begin exactly where its audio
does, and the total lands back on the sum of the scene durations. Audio is concatenated
and never cross-faded, so no word is ever ramped down mid-sentence.

Captions are baked into the frames by the HTML renderer (this ffmpeg build has no
subtitles filter), so there is nothing to burn in here.

Everything runs with ``cwd`` set to the work directory so ffmpeg takes bare filenames.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from concurrent import futures
from dataclasses import dataclass
from pathlib import Path

from .errors import RenderUnavailable

log = logging.getLogger(__name__)

#: Scene-to-scene transition, and therefore also the hold appended to every scene but
#: the last.
SCENE_XFADE_S = 0.4

#: A dip through black, NOT a straight dissolve.
#:
#: `transition=fade` was tried first and rendered correctly, but it looks wrong: the
#: HTML renderer burns the whole narration into a caption bar at the bottom of the
#: frame and a heading near the top, so both scenes' blocks of text sit in the same
#: two places. Cross-dissolving them puts two paragraphs on top of each other at ~50%
#: each for a quarter of a second, six times a reel, which reads as a rendering fault
#: rather than as a transition. `fadeblack` never shows two scenes at once. It is also
#: quick — measured on a 30fps render, only ~3 frames are near-black, and the ease back
#: in takes the remaining ~300ms — so it reads as a beat between sections, not a
#: blackout. `slideup` also avoids the overlap but pushes the whole frame, footage
#: included, which is a lot of motion to impose with no reduced-motion escape hatch.
SCENE_TRANSITION = "fadeblack"

#: How long one reveal step takes to appear. Clamped to half a step below, so a scene
#: with many short steps does not spend all of itself mid-fade.
STEP_FADE_S = 0.3

#: Opening fade from black, applied once to the finished video.
OPEN_FADE_S = 0.4


@dataclass(frozen=True)
class Segment:
    #: The scene's build-up, one frame per reveal step; frames split the narration
    #: length evenly. A single frame simply holds.
    pngs: list[Path]
    wav: Path
    duration_ms: int
    #: Looping background footage; the PNGs (captured with alpha) are overlaid on it.
    clip: Path | None = None


#: Ceiling on one ffmpeg invocation. Generous — a whole-video join pass on a slow
#: box takes tens of seconds, not minutes — but bounded, because an ffmpeg that
#: hangs has nothing to time it out: the job sits in `rendering` forever and the
#: browser polls it forever. Now that segments encode in a pool, one stuck process
#: would also hold a worker for the rest of the run.
_FFMPEG_TIMEOUT_SECONDS = 600


def _run(cmd: list[str], cwd: Path) -> None:
    try:
        result = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            timeout=_FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"ffmpeg did not finish within {_FFMPEG_TIMEOUT_SECONDS}s: {' '.join(cmd[:6])}…"
        ) from exc
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg failed ({result.returncode}):\n{tail}")


def _still_filter(width: int, height: int, fps: int) -> str:
    """A single still, held. No zoom and no fade of its own — the join pass owns the
    opening fade and every scene-to-scene transition."""
    return f"[0:v]scale={width}:{height},fps={fps},setsar=1[v]"


def _reveal_filter(
    width: int, height: int, fps: int, *, steps: int, dur_s: float, footage: bool
) -> str:
    """Cross-faded overlays: frame ``i`` of the build-up fades in over its slice of the
    narration and fades out again as frame ``i+1`` fades in. Input 0 is the background
    (looping clip, or black under opaque frames); inputs 1..steps are the PNGs.

    The captured frames are CUMULATIVE states of the build-up, so fading state ``i``
    out under state ``i+1`` fading in is exactly a cross-fade between two stills that
    differ by one component — what the eye sees is that component arriving. Stacking
    them instead (leaving each one on and adding the next over it) would work for the
    opaque frames but compound the translucent scrim of the over-footage ones, so the
    frame darkens a step per reveal.
    """
    if footage:
        bg = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},setsar=1[bg];"
        )
    else:
        bg = f"[0:v]fps={fps},setsar=1[bg];"

    slice_s = dur_s / steps
    # Half a slice at most, so a step's fade-in has always finished before its
    # fade-out begins — two `fade` filters on one stream must not overlap.
    fade_s = min(STEP_FADE_S, slice_s / 2)

    chain = bg
    for i in range(steps):
        start = slice_s * i
        # yuva420p first so both fades act on ALPHA rather than towards black: the
        # frames are composited over the background, not shown on their own.
        stage = f"[{i + 1}:v]fps={fps},format=yuva420p"
        if i > 0:
            stage += f",fade=t=in:st={start:.3f}:d={fade_s:.3f}:alpha=1"
        if i < steps - 1:
            stage += f",fade=t=out:st={start + slice_s:.3f}:d={fade_s:.3f}:alpha=1"
        chain += f"{stage}[p{i}];"

    # `fade` holds its end state outside its window — transparent before a fade-in and
    # after a fade-out — so no `enable` expression is needed to keep a step off screen.
    prev = "bg"
    for i in range(steps):
        label = "v" if i == steps - 1 else f"o{i}"
        chain += f"[{prev}][p{i}]overlay[{label}];"
        prev = label
    return chain.rstrip(";")


def _join_filter(count: int, durations: list[float]) -> str:
    """Transition between the segments and concatenate the narration under them.

    Each join's offset is where the accumulated video has reached minus the overlap;
    because every segment but the last carries ``SCENE_XFADE_S`` of padding, that
    offset is precisely the sum of the PRECEDING narration durations, which is also
    where the concatenated audio hands over. See the module docstring.
    """
    chain = ""
    prev = "[0:v]"
    running = durations[0] + (SCENE_XFADE_S if count > 1 else 0.0)
    for index in range(1, count):
        offset = running - SCENE_XFADE_S
        label = f"[x{index}]"
        chain += (
            f"{prev}[{index}:v]xfade=transition={SCENE_TRANSITION}:"
            f"duration={SCENE_XFADE_S}:offset={offset:.3f}{label};"
        )
        prev = label
        running = offset + durations[index] + (
            SCENE_XFADE_S if index < count - 1 else 0.0
        )
    chain += f"{prev}fade=t=in:st=0:d={OPEN_FADE_S},format=yuv420p[v];"

    # apad then atrim pins every scene's audio to exactly the length its visuals were
    # encoded for, whichever side the measured wav fell on.
    for index, dur in enumerate(durations):
        chain += (
            f"[{count + index}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"apad=whole_dur={dur:.3f},atrim=0:{dur:.3f},asetpts=N/SR/TB[a{index}];"
        )
    chain += "".join(f"[a{i}]" for i in range(count)) + f"concat=n={count}:v=0:a=1[a]"
    return chain


def compose(segments: list[Segment], out_mp4: Path, *, fps: int, width: int, height: int) -> Path:
    """Render each segment, then transition between them into ``out_mp4``.

    :raises RenderUnavailable: if ffmpeg is not on PATH
    :raises RuntimeError: if ffmpeg rejects an input
    """
    if shutil.which("ffmpeg") is None:
        raise RenderUnavailable("ffmpeg is not installed (brew install ffmpeg)")
    if not segments:
        raise RuntimeError("nothing to compose: no scenes")

    work = out_mp4.parent
    work.mkdir(parents=True, exist_ok=True)
    last = len(segments) - 1
    seg_names: list[str] = []
    durations: list[float] = []
    commands: list[list[str]] = []

    for index, segment in enumerate(segments):
        dur_s = max(0.8, segment.duration_ms / 1000)
        durations.append(dur_s)
        # Hold the final frame for the length of the transition, so the next scene
        # arrives over padding instead of over the tail of this scene's narration.
        seg_len = dur_s + (SCENE_XFADE_S if index < last else 0.0)
        seg_name = f"seg{index}.mp4"
        steps = len(segment.pngs)
        if segment.clip is None and steps == 1:
            inputs = [
                "-loop", "1", "-framerate", str(fps), "-i", segment.pngs[0].name,
                "-filter_complex", _still_filter(width, height, fps),
            ]
        else:
            # The clip's own audio is never mapped; narration is the soundtrack, and
            # it is muxed in the join pass rather than per segment.
            if segment.clip is not None:
                background = ["-stream_loop", "-1", "-i", str(segment.clip.resolve())]
            else:
                background = ["-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={fps}"]
            inputs = [
                *background,
                *(
                    part
                    for png in segment.pngs
                    for part in ("-loop", "1", "-framerate", str(fps), "-i", png.name)
                ),
                "-filter_complex",
                _reveal_filter(
                    width, height, fps, steps=steps, dur_s=dur_s,
                    footage=segment.clip is not None,
                ),
            ]
        commands.append(
            [
                "ffmpeg", "-y",
                *inputs,
                "-map", "[v]",
                "-t", f"{seg_len:.3f}",
                "-r", str(fps),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                seg_name,
            ]
        )
        seg_names.append(seg_name)

    # Segments share nothing: each reads its own stills and writes its own file, so
    # they encode concurrently. Capped rather than unbounded because ffmpeg is already
    # threaded internally — past a few, the encodes only contend for the same cores,
    # and a long storyboard would otherwise launch a dozen at once.
    workers = max(1, min(4, (os.cpu_count() or 2) - 1, len(commands)))
    if workers == 1 or len(commands) == 1:
        for cmd in commands:
            _run(cmd, cwd=work)
    else:
        with futures.ThreadPoolExecutor(max_workers=workers) as pool:
            # list() re-raises the first failure, and the context manager waits for
            # the rest, so a broken scene cannot leave the join pass reading a
            # half-written segment.
            list(pool.map(lambda cmd: _run(cmd, cwd=work), commands))

    _run(
        [
            "ffmpeg", "-y",
            *(part for name in seg_names for part in ("-i", name)),
            *(part for segment in segments for part in ("-i", segment.wav.name)),
            "-filter_complex", _join_filter(len(segments), durations),
            "-map", "[v]", "-map", "[a]",
            "-r", str(fps),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-c:a", "aac", "-ar", "44100",
            "-movflags", "+faststart",
            out_mp4.name,
        ],
        cwd=work,
    )
    log.info("composed %s from %d scenes", out_mp4, len(segments))
    return out_mp4
