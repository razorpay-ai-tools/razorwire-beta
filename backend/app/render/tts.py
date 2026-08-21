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
import re
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
_SAY_RATE = 22050  # wav sample rate
_SAY_WPM = 168  # speech pace (words/min); a touch under the ~175 default, less rushed
_MIN_MS = 800  # the schema floor for scene.durationMs

#: say embedded pause commands, injected at punctuation so it reads like a person.
_PAUSE_SENTENCE = re.compile(r"([.!?])(\s+)")
_PAUSE_CLAUSE = re.compile(r"([,;:])(\s+)")


@dataclass(frozen=True)
class Voiced:
    """One scene's narration, spoken."""

    index: int
    wav_path: Path
    duration_ms: int
    #: For a stepped diagram scene: the start time (ms) of each hop's beat within the
    #: scene audio, so the render can reveal each hop exactly when its beat is spoken.
    beat_starts: list[int] | None = None


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


def _humanize(text: str) -> str:
    """Insert brief pauses so `say` follows punctuation like a person speaking.
    ``[[slnc N]]`` is a say embedded command for N ms of silence."""
    text = _PAUSE_SENTENCE.sub(r"\1 [[slnc 340]]\2", text)
    text = _PAUSE_CLAUSE.sub(r"\1 [[slnc 160]]\2", text)
    return text


def _synth_say(text: str, path: Path) -> bool:
    """macOS `say` -> WAV. Returns False if `say` is absent or fails."""
    if shutil.which("say") is None:
        return False
    try:
        subprocess.run(
            ["say", "-o", str(path), "--data-format=LEI16@%d" % _SAY_RATE,
             "-r", str(_SAY_WPM), _humanize(text)],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.warning("say failed: %s", exc)
        return False
    return path.exists() and path.stat().st_size > 44  # bigger than a bare WAV header


_KOKORO_PIPELINES: dict[str, object] = {}


def _kokoro_pipeline(lang_code: str):
    """Build and cache one KPipeline per language. The 82M model loads once per
    process, not once per hop — per-beat voicing calls the synthesizer many times."""
    pipe = _KOKORO_PIPELINES.get(lang_code)
    if pipe is None:
        from kokoro import KPipeline  # type: ignore

        pipe = KPipeline(lang_code=lang_code)
        _KOKORO_PIPELINES[lang_code] = pipe
    return pipe


def _synth_kokoro(text: str, path: Path, voice: str) -> bool:
    """Kokoro-82M -> WAV. Returns False if the package/model is unavailable."""
    try:
        pipeline = _kokoro_pipeline("a")
    except Exception as exc:  # not installed, or torch/model missing
        log.info("kokoro unavailable (%s); falling back", exc)
        return False
    try:
        rate = 24000
        chunks = [audio for _, _, audio in pipeline(text, voice=voice)]
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


def _concat_wavs(paths: list[Path], out: Path) -> None:
    """Concatenate same-format WAVs with the stdlib (no ffmpeg needed)."""
    with wave.open(str(paths[0]), "rb") as first:
        params = first.getparams()
    with wave.open(str(out), "wb") as combined:
        combined.setparams(params)
        for path in paths:
            with wave.open(str(path), "rb") as clip:
                combined.writeframes(clip.readframes(clip.getnframes()))


def voice_steps(says: list[str], work_dir: Path, index: int, **kwargs) -> tuple[Path, int, list[int]]:
    """Speak each hop's ``say`` as its own clip, concatenate into one scene wav, and
    return ``(scene_wav, total_ms, beat_start_times_ms)``.

    Beat starts are measured off the real clips, so a diagram reveal keyed to them
    stays exactly in sync with the voice.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    beat_paths: list[Path] = []
    durations: list[int] = []
    for i, say in enumerate(says):
        beat = work_dir / f"scene{index}_beat{i}.wav"
        synthesize(say, beat, **kwargs)
        beat_paths.append(beat)
        durations.append(_wav_duration_ms(beat))
    scene_wav = work_dir / f"scene{index}.wav"
    _concat_wavs(beat_paths, scene_wav)
    starts = [sum(durations[:i]) for i in range(len(durations))]
    return scene_wav, _wav_duration_ms(scene_wav), starts
