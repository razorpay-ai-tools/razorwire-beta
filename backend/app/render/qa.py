"""Post-render checks on the finished MP4: loudness, and did it actually render.

Both engines end with a file nobody has watched. Two classes of defect get through
every gate upstream, because neither is visible in the storyboard, the HTML or the
wav:

  1. **Loudness drifts between reels.** Scene length comes from the narration, and
     the narration comes from whatever TTS backend was available — Kokoro at one
     level, macOS `say` at another, a silent track at none. A feed where one reel
     is quiet and the next is loud reads as broken, and the fix is not a volume
     slider on each post.
  2. **A reel renders black, frozen or silent.** ffmpeg exits 0 on plenty of things
     that produce no picture: a scene that never signalled ready and screenshotted a
     blank page, a wav that came back as digital silence, a filtergraph that held one
     frame for the whole segment. The job is marked `published` either way.

Everything here is ffmpeg, which is already a hard dependency. No new packages, no
network, no models.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import RenderUnavailable

log = logging.getLogger(__name__)

#: Integrated loudness target, LUFS. -16 is the speech-forward default (Apple
#: Podcasts); -14 is what YouTube and Spotify normalise playback to. The reel is
#: narration over an optional quiet bed, so it sits with speech rather than music.
TARGET_LUFS = -16.0

#: True-peak ceiling, dBTP. NOT 0: AAC generates intersample peaks on decode that can
#: exceed the encoded peak by 1-3 dB, and a 0 dBTP master clips on some decoders.
TARGET_TRUE_PEAK = -1.5

#: Loudness range. The EBU default; wide enough that a quiet aside survives.
TARGET_LRA = 11.0
_LOUDNORM = f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK}:LRA={TARGET_LRA}"

#: Below this, loudnorm is measuring the noise floor rather than speech. ffmpeg's own
#: gate bottoms out near -70 LUFS, so anything this quiet is silence, and "normalising"
#: it only amplifies hiss.
SILENCE_FLOOR_LUFS = -50.0

#: Already within this much of the target: leave it alone. The filter is not a no-op
#: on audio that needs no change — it still resamples and re-encodes.
LOUDNESS_TOLERANCE_LU = 1.0

_TIMEOUT = 600


@dataclass(frozen=True)
class Loudness:
    integrated: float
    true_peak: float
    lra: float
    threshold: float
    offset: float


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    if shutil.which("ffmpeg") is None:
        raise RenderUnavailable("ffmpeg is not installed (brew install ffmpeg)")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)


def measure(mp4: Path) -> Loudness | None:
    """Pass one: what the file actually measures.

    ``loudnorm`` writes its JSON to stderr after the null muxer has consumed the
    stream, so the report is the LAST json object in the output, not the first thing
    that looks like one.
    """
    result = _run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4), "-vn",
            "-af",
            f"{_LOUDNORM}:print_format=json",
            "-f", "null", "-",
        ]
    )
    blobs = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr, re.S)
    if not blobs:
        log.warning("loudnorm produced no measurement for %s", mp4)
        return None
    try:
        data = json.loads(blobs[-1])
        return Loudness(
            integrated=float(data["input_i"]),
            true_peak=float(data["input_tp"]),
            lra=float(data["input_lra"]),
            threshold=float(data["input_thresh"]),
            offset=float(data["target_offset"]),
        )
    except (ValueError, KeyError) as exc:
        log.warning("could not parse loudnorm report for %s: %s", mp4, exc)
        return None


def normalize_loudness(mp4: Path) -> bool:
    """Two-pass EBU R128 normalisation, in place. Returns True if the file changed.

    Two passes rather than one because a single pass only *estimates* the input and
    lands within roughly 1 LU of target — which is exactly the drift that makes two
    reels in the same feed sound different.

    Dynamic mode (no ``linear=true``) on purpose: this is speech, and the linear mode
    that suits music applies one constant gain, which leaves a quiet scene quiet.

    The video stream is copied, so only the audio is decoded and re-encoded.
    """
    measured = measure(mp4)
    if measured is None:
        return False
    if measured.integrated <= SILENCE_FLOOR_LUFS:
        log.warning(
            "%s measures %.1f LUFS — silent or near-silent, not normalising", mp4,
            measured.integrated,
        )
        return False
    if abs(measured.integrated - TARGET_LUFS) <= LOUDNESS_TOLERANCE_LU:
        log.info("%s already at %.1f LUFS, leaving it alone", mp4, measured.integrated)
        return False

    out = mp4.with_suffix(".norm.mp4")
    result = _run(
        [
            "ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(mp4),
            "-af",
            f"{_LOUDNORM}:measured_I={measured.integrated}:measured_TP={measured.true_peak}"
            f":measured_LRA={measured.lra}:measured_thresh={measured.threshold}"
            f":offset={measured.offset}",
            "-c:v", "copy",
            # loudnorm resamples to 192 kHz internally, so the output rate has to be
            # stated or the file carries it.
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(out),
        ]
    )
    if result.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-6:])
        log.warning("loudness normalisation failed for %s, keeping the original:\n%s", mp4, tail)
        out.unlink(missing_ok=True)
        return False
    out.replace(mp4)
    log.info("normalised %s from %.1f to %.1f LUFS", mp4, measured.integrated, TARGET_LUFS)
    return True


def inspect(mp4: Path, *, expected_ms: int | None = None) -> list[str]:
    """Findings on the finished file. Empty list means nothing looked wrong.

    Deliberately returns findings rather than raising: a reel with a 3-second frozen
    stretch is still worth publishing, and a human reading the job log is a better
    judge than a threshold. The caller decides what is fatal.
    """
    findings: list[str] = []

    if not mp4.is_file() or mp4.stat().st_size == 0:
        return [f"{mp4.name} is missing or empty"]

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type", "-of", "json", str(mp4),
        ],
        capture_output=True, text=True, timeout=_TIMEOUT,
    )
    try:
        meta = json.loads(probe.stdout)
        duration = float(meta["format"]["duration"])
        kinds = {stream.get("codec_type") for stream in meta.get("streams", [])}
    except (ValueError, KeyError):
        return [f"{mp4.name} has no readable duration — the file is probably truncated"]

    if "audio" not in kinds:
        findings.append("no audio stream: the reel is silent")
    if "video" not in kinds:
        findings.append("no video stream")
    if expected_ms is not None and abs(duration * 1000 - expected_ms) > 1000:
        findings.append(
            f"duration is {duration:.1f}s but the narration measured "
            f"{expected_ms / 1000:.1f}s — picture and voice disagree"
        )

    # One pass, three detectors.
    #
    # `blackdetect` wants a picture-black ratio, and 0.98 is its own default: a frame
    # that is 98% black reads as black even with a caption still on it.
    #
    # `freezedetect`'s threshold is derived from the reel's own length rather than
    # fixed. A razorwire scene IS a held frame — a title card sits still for its whole
    # narration, and the ffmpeg engine renders most scenes as one still. At the usual
    # d=2.0 every scene of every reel is a finding, which is a detector that only ever
    # cries wolf. At 90% of the duration it fires on one thing: a reel where nothing
    # moved at all, which is the failure worth catching.
    freeze_d = max(5.0, duration * 0.9)
    result = _run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(mp4),
            "-vf", f"blackdetect=d=1.0:pic_th=0.98,freezedetect=n=0.001:d={freeze_d:.2f}",
            "-af", "silencedetect=n=-45dB:d=2.0",
            "-f", "null", "-",
        ]
    )
    log_text = result.stderr

    for match in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", log_text):
        start, end = float(match.group(1)), float(match.group(2))
        # The opening fade from black is authored, not a fault — but only a SHORT run
        # at the head is a fade. Exempting everything that starts at zero is how a
        # reel that is black end to end reports nothing at all.
        if start <= 0.5 and (end - start) < 1.5:
            continue
        findings.append(f"black frames from {start:.1f}s to {end:.1f}s")

    if re.search(r"freeze_start: ([\d.]+)", log_text):
        findings.append(
            f"the picture is static for essentially the whole reel ({duration:.1f}s) — "
            "nothing rendered but the first frame"
        )

    for match in re.finditer(
        r"silence_start: ([\d.-]+)(?:.*?silence_duration: ([\d.]+))?", log_text, re.S
    ):
        start = float(match.group(1))
        span = f" for {float(match.group(2)):.1f}s" if match.group(2) else ""
        findings.append(f"silence from {max(start, 0.0):.1f}s{span}")

    return findings
