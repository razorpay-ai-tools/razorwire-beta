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
    #: The scene's frames, in playback order — one wherever the reveal step or the
    #: subtitle changed. A single frame simply holds.
    pngs: list[Path]
    wav: Path
    duration_ms: int
    #: Looping background footage; the PNGs (captured with alpha) are overlaid on it.
    clip: Path | None = None
    #: ``(png, start_ms, end_ms)`` subtitle plates, composited ON TOP of the finished
    #: build-up and switched with a hard cut. Separate from ``pngs`` because they are
    #: timed to the voice rather than evenly spaced, and because cross-fading them
    #: would show two different subtitles at once.
    captions: list[tuple[Path, int, int]] | None = None


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
    width: int,
    height: int,
    fps: int,
    *,
    frame_s: list[float],
    footage: bool,
    caption_windows: list[tuple[float, float]] | None = None,
) -> str:
    """Cross-faded overlays: frame ``i`` holds for ``frame_s[i]`` and fades out as frame
    ``i+1`` fades in. Input 0 is the background (looping clip, or black under opaque
    frames); inputs 1..n are the build-up PNGs, and n+1.. are the subtitle plates.

    The captured frames are CUMULATIVE states of the build-up, so fading state ``i``
    out under state ``i+1`` fading in is exactly a cross-fade between two stills that
    differ by one component — what the eye sees is that component arriving. Stacking
    them instead (leaving each one on and adding the next over it) would work for the
    opaque frames but compound the translucent scrim of the over-footage ones, so the
    frame darkens a step per reveal.

    Subtitles go on last and are gated with ``enable`` rather than faded, so each one
    CUTS. Cross-fading them put the outgoing and incoming line on screen together,
    both legible, and dimmed everything under them for the length of the dissolve —
    which is why the two layers are captured and composited separately at all.
    """
    if footage:
        bg = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},setsar=1[bg];"
        )
    else:
        bg = f"[0:v]fps={fps},setsar=1[bg];"

    steps = len(frame_s)
    starts = [0.0]
    for span in frame_s[:-1]:
        starts.append(starts[-1] + span)

    def transition_at(index: int) -> float:
        """The cross-fade shared by frame ``index-1`` going out and ``index`` coming in.

        Half of the SHORTER neighbour, so it can never outlast either: two `fade`
        filters on one stream must not overlap, and a short cue between two long ones
        would otherwise be fading for its entire life.
        """
        return min(STEP_FADE_S, frame_s[index - 1] / 2, frame_s[index] / 2)

    chain = bg
    for i in range(steps):
        # yuva420p first so both fades act on ALPHA rather than towards black: the
        # frames are composited over the background, not shown on their own.
        stage = f"[{i + 1}:v]fps={fps},format=yuva420p"
        if i > 0:
            stage += f",fade=t=in:st={starts[i]:.3f}:d={transition_at(i):.3f}:alpha=1"
        if i < steps - 1:
            stage += f",fade=t=out:st={starts[i + 1]:.3f}:d={transition_at(i + 1):.3f}:alpha=1"
        chain += f"{stage}[p{i}];"

    windows = caption_windows or []

    # `fade` holds its end state outside its window — transparent before a fade-in and
    # after a fade-out — so no `enable` expression is needed to keep a step off screen.
    prev = "bg"
    for i in range(steps):
        last_content = i == steps - 1
        label = ("v" if not windows else "vc") if last_content else f"o{i}"
        chain += f"[{prev}][p{i}]overlay[{label}];"
        prev = label

    # The plates are mutually exclusive by construction — cues are gapless and
    # non-overlapping — so stacking them cannot compound their alpha.
    # Commas inside `between()` are escaped, not quoted: this string is one
    # filter_complex argument passed without a shell, so ffmpeg's own parser would
    # otherwise read them as argument separators.
    for position, (start, end) in enumerate(windows):
        source_index = steps + 1 + position
        chain += f"[{source_index}:v]fps={fps},format=yuva420p[cp{position}];"
        label = "v" if position == len(windows) - 1 else f"co{position}"
        chain += (
            f"[{prev}][cp{position}]"
            f"overlay=enable='between(t\\,{start:.3f}\\,{end:.3f})'[{label}];"
        )
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
        captions = segment.captions or []
        # Cue times are measured against the wav; the segment is encoded at `dur_s`,
        # which the schema floor can raise. Scale so the last subtitle still lands on
        # the last word instead of drifting a little further out every scene.
        scale = dur_s / (segment.duration_ms / 1000) if segment.duration_ms > 0 else 1.0
        caption_windows = [
            (start_ms / 1000 * scale, end_ms / 1000 * scale)
            for _, start_ms, end_ms in captions
        ]
        if segment.clip is None and steps == 1 and not captions:
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
            # The build-up is evenly spaced across the scene; only the subtitles are
            # timed to the voice, and they are a separate layer now.
            frame_s = [dur_s / steps] * steps
            inputs = [
                *background,
                *(
                    part
                    for png in segment.pngs
                    for part in ("-loop", "1", "-framerate", str(fps), "-i", png.name)
                ),
                *(
                    part
                    for png, _, _ in captions
                    for part in ("-loop", "1", "-framerate", str(fps), "-i", png.name)
                ),
                "-filter_complex",
                _reveal_filter(
                    width, height, fps, frame_s=frame_s,
                    footage=segment.clip is not None,
                    caption_windows=caption_windows,
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
