"""Frames + narration -> a single MP4, via ffmpeg.

Each scene becomes a still that ffmpeg animates with a slow Ken Burns zoom and holds
for exactly its narration's measured length; scenes are then concatenated. Captions
are baked into the frames by the HTML renderer (this ffmpeg build has no subtitles
filter), so there is nothing to burn in here.

Everything runs with ``cwd`` set to the work directory so ffmpeg takes bare filenames.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import RenderUnavailable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Segment:
    png: Path
    wav: Path
    duration_ms: int


def _run(cmd: list[str], cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg failed ({result.returncode}):\n{tail}")


def _scene_filter(width: int, height: int, fps: int, frames: int) -> str:
    return (
        f"[0:v]scale={width}:{height},"
        f"zoompan=z='min(zoom+0.0006,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={width}x{height}:fps={fps}[v];[1:a]apad[a]"
    )


def compose(segments: list[Segment], out_mp4: Path, *, fps: int, width: int, height: int) -> Path:
    """Render each segment, then concatenate into ``out_mp4``.

    :raises RenderUnavailable: if ffmpeg is not on PATH
    :raises RuntimeError: if ffmpeg rejects an input
    """
    if shutil.which("ffmpeg") is None:
        raise RenderUnavailable("ffmpeg is not installed (brew install ffmpeg)")
    if not segments:
        raise RuntimeError("nothing to compose: no scenes")

    work = out_mp4.parent
    work.mkdir(parents=True, exist_ok=True)
    seg_files: list[str] = []

    for index, segment in enumerate(segments):
        dur_s = max(0.8, segment.duration_ms / 1000)
        frames = max(1, round(fps * dur_s))
        seg_name = f"seg{index}.mp4"
        _run(
            [
                "ffmpeg", "-y",
                "-i", segment.png.name,
                "-i", segment.wav.name,
                "-filter_complex", _scene_filter(width, height, fps, frames),
                "-map", "[v]", "-map", "[a]",
                "-t", f"{dur_s:.3f}",
                "-r", str(fps),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                "-c:a", "aac", "-ar", "44100",
                seg_name,
            ],
            cwd=work,
        )
        seg_files.append(seg_name)

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{name}'\n" for name in seg_files), encoding="utf-8")
    _run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat.name,
            "-c", "copy", "-movflags", "+faststart",
            out_mp4.name,
        ],
        cwd=work,
    )
    log.info("composed %s from %d scenes", out_mp4, len(segments))
    return out_mp4
