"""Text to speech, and the measured duration that drives scene length.

Three backends, tried in order for ``render_tts="auto"``:

    kokoro   Kokoro-82M, local and open-weight. The production voice; no egress.
    say      macOS `say`. Always present on a Mac, no install, no model download.
    silent   a silent track of an *estimated* length. Last resort so a render never
             hard-fails just because no voice is available.

The number that matters is the **measured** duration of the wav, because the
storyboard contract's whole anti-desync rule is that scene length comes from the
audio, never from the model. Duration is read back off the file with the stdlib
``wave`` module — no extra dependency.
"""

from __future__ import annotations

import logging
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)

#: Spoken-word pace used only to *estimate* a silent clip's length.
_WORDS_PER_SECOND = 160 / 60
_SAY_RATE = 22050
_MIN_MS = 800  # the schema floor for scene.durationMs


@dataclass(frozen=True)
class Voiced:
    """One scene's narration, spoken."""

    index: int
    wav_path: Path
    duration_ms: int


def _wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        frames, rate = handle.getnframes(), handle.getframerate()
    if rate <= 0:
        return 0
    return int(round(frames / rate * 1000))


def _estimate_ms(text: str) -> int:
    words = max(len(text.split()), 1)
    return int(round(words / _WORDS_PER_SECOND * 1000))


def _clamp(ms: int) -> int:
    return max(_MIN_MS, min(ms, settings.render_scene_max_ms))


def _write_silence(path: Path, ms: int, rate: int = _SAY_RATE) -> None:
    count = int(rate * ms / 1000)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * count)


def _synth_say(text: str, path: Path) -> bool:
    """macOS `say` -> WAV. Returns False if `say` is absent or fails."""
    if shutil.which("say") is None:
        return False
    try:
        subprocess.run(
            ["say", "-o", str(path), "--data-format=LEI16@%d" % _SAY_RATE, text],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.warning("say failed: %s", exc)
        return False
    return path.exists() and path.stat().st_size > 44  # bigger than a bare WAV header


def _synth_kokoro(text: str, path: Path, voice: str) -> bool:
    """Kokoro-82M -> WAV. Returns False if the package/model is unavailable."""
    try:
        from kokoro import KPipeline  # type: ignore
    except Exception as exc:  # not installed, or torch missing
        log.info("kokoro unavailable (%s); falling back", exc)
        return False
    try:
        # Kokoro names a voice <lang><gender>_<name>, and the pipeline needs the
        # matching G2P: "a" American, "b" British, "h" Hindi. This was pinned to "a",
        # so any non-American voice was phonemised as American and came out wrong —
        # which made the voice setting look like it did nothing.
        pipeline = KPipeline(lang_code=voice[0] if voice else "a")
        rate = 24000
        chunks = [audio for _, _, audio in pipeline(text, voice=voice, speed=settings.kokoro_speed)]
        if not chunks:
            return False
        _write_float_wav(path, chunks, rate)
    except Exception as exc:  # pragma: no cover - only exercised when kokoro is present
        log.warning("kokoro synthesis failed: %s", exc)
        return False
    return path.exists()


def _write_float_wav(path: Path, chunks: list, rate: int) -> None:
    """Concatenate float samples in [-1, 1] and write a 16-bit mono WAV."""
    try:
        import numpy as np  # kokoro pulls numpy in

        samples = np.concatenate([np.asarray(chunk).ravel() for chunk in chunks])
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    except Exception:  # numpy absent: slow but correct
        flat = [float(value) for chunk in chunks for value in chunk]
        pcm = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767)) for value in flat)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)


def synthesize(text: str, path: Path, *, backend: str | None = None, voice: str | None = None) -> int:
    """Speak ``text`` into ``path`` (a .wav) and return its measured duration in ms.

    Never raises for a missing engine: it degrades kokoro -> say -> silence so a
    render is always producible. The returned duration is clamped to the schema
    floor and the per-scene ceiling.
    """
    backend = backend or settings.render_tts
    voice = voice or settings.kokoro_voice
    path.parent.mkdir(parents=True, exist_ok=True)

    order = {
        "auto": ("kokoro", "say", "silent"),
        "kokoro": ("kokoro", "say", "silent"),
        "say": ("say", "silent"),
        "silent": ("silent",),
    }.get(backend, ("kokoro", "say", "silent"))

    for engine in order:
        if engine == "kokoro" and _synth_kokoro(text, path, voice):
            break
        if engine == "say" and _synth_say(text, path):
            break
        if engine == "silent":
            _write_silence(path, _clamp(_estimate_ms(text)))
            break
    else:  # pragma: no cover - the "silent" branch always terminates the loop
        _write_silence(path, _clamp(_estimate_ms(text)))

    measured = _wav_duration_ms(path)
    return _clamp(measured if measured > 0 else _estimate_ms(text))


def voice_scenes(narrations: list[str], work_dir: Path, **kwargs) -> list[Voiced]:
    """Speak every scene's narration into ``work_dir`` and return the results in order."""
    work_dir.mkdir(parents=True, exist_ok=True)
    out: list[Voiced] = []
    for index, text in enumerate(narrations):
        wav = work_dir / f"scene{index}.wav"
        duration = synthesize(text, wav, **kwargs)
        out.append(Voiced(index=index, wav_path=wav, duration_ms=duration))
    return out
