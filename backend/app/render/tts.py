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
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import settings

log = logging.getLogger(__name__)

#: One KPipeline per language, reused across scenes and across jobs.
#:
#: Constructing it loads Kokoro-82M, which measured ~3s — and it was constructed
#: once PER SCENE, so a seven-scene reel paid for seven loads before speaking a
#: word. The lock covers synthesis as well as construction: a torch module is not
#: safe to call from two threads at once, and two jobs can voice concurrently in
#: the background threadpool. Serialising costs nothing real, because synthesis is
#: compute-bound and would contend for the same cores anyway.
_PIPELINES: dict[str, object] = {}
_PIPELINE_LOCK = threading.Lock()

#: Spoken-word pace used only to *estimate* a silent clip's length.
_WORDS_PER_SECOND = 160 / 60
_SAY_RATE = 22050
_MIN_MS = 800  # the schema floor for scene.durationMs


#: A subtitle line is read by the eye in one glance, so it is short and it changes
#: with the voice. Past roughly this much text the line wraps to three rows in a 9:16
#: frame and stops being glanceable; past this many words it outlasts the phrase it
#: belongs to. Cues also break at sentence punctuation regardless of either.
_CUE_MAX_CHARS = 42
_CUE_MAX_WORDS = 7
#: A cue shorter than this flickers. Merged forward into the next one instead.
_CUE_MIN_MS = 500


@dataclass(frozen=True)
class Cue:
    """One subtitle line, and the window of the wav in which it is spoken."""

    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class Voiced:
    """One scene's narration, spoken."""

    index: int
    wav_path: Path
    duration_ms: int
    #: Speech-synced subtitle lines. Empty when the backend cannot time words, which
    #: callers must treat as "show the whole narration" rather than "show nothing".
    cues: tuple[Cue, ...] = ()


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


def _is_punctuation(token_text: str) -> bool:
    return bool(token_text) and not any(char.isalnum() for char in token_text)


#: Punctuation that joins a word to the NEXT one rather than ending it. Kokoro splits
#: "payments-upi" into three tokens, so gluing the hyphen backwards and then starting a
#: fresh word rendered the subtitle as "payments- upi" — a service name broken in half.
#:
#: Deliberately excludes ".", which is far more often a sentence end than a decimal
#: point; treating it as a connector would run two sentences together as "here.Next".
_WORD_CONNECTORS = ("-", "'", "’", "/", "_")


def _words_from_result(result: Any, offset_s: float) -> list[tuple[str, float, float]]:
    """Kokoro tokens -> (word, start_s, end_s), shifted by this chunk's offset.

    Kokoro times each chunk from ITS OWN zero, so a multi-chunk narration would
    otherwise restart its subtitles partway through. Punctuation arrives as its own
    token and is glued onto the preceding word: a line break before a lone "." is
    never what you want, and its timestamp is the pause, not a word.
    """
    words: list[tuple[str, float, float]] = []
    for token in getattr(result, "tokens", None) or []:
        raw = (getattr(token, "text", "") or "").strip()
        start, end = getattr(token, "start_ts", None), getattr(token, "end_ts", None)
        if not raw or start is None or end is None:
            continue
        start, end = float(start) + offset_s, float(end) + offset_s
        if _is_punctuation(raw) and words:
            prev_text, prev_start, _ = words[-1]
            words[-1] = (prev_text + raw, prev_start, end)
            continue
        # A word right after a connector completes the token the connector opened.
        if words and words[-1][0].endswith(_WORD_CONNECTORS):
            prev_text, prev_start, _ = words[-1]
            words[-1] = (prev_text + raw, prev_start, end)
            continue
        words.append((raw, start, end))
    return words


def _group_cues(words: list[tuple[str, float, float]], total_ms: int) -> tuple[Cue, ...]:
    """Words -> subtitle lines, broken at sentence ends and at a glanceable length."""
    if not words:
        return ()

    lines: list[list[tuple[str, float, float]]] = [[]]
    for word in words:
        current = lines[-1]
        candidate = " ".join(w[0] for w in [*current, word])
        if current and (len(candidate) > _CUE_MAX_CHARS or len(current) >= _CUE_MAX_WORDS):
            lines.append([word])
        else:
            current.append(word)
        # A sentence that ended is a break the ear already heard; honour it even if
        # the line is short, so a cue never straddles two sentences.
        if word[0].endswith((".", "!", "?")) and lines[-1]:
            lines.append([])
    lines = [line for line in lines if line]

    cues = [
        Cue(
            text=" ".join(w[0] for w in line),
            start_ms=int(round(line[0][1] * 1000)),
            end_ms=int(round(line[-1][2] * 1000)),
        )
        for line in lines
    ]

    # The first cue starts when the first word does, which leaves the frame captionless
    # for the leading silence. Pull it back to zero instead.
    cues[0] = Cue(cues[0].text, 0, cues[0].end_ms)
    # Each cue holds until the next begins, so there is no captionless gap between
    # words, and the last one holds to the end of the scene.
    stretched = [
        Cue(cue.text, cue.start_ms, cues[i + 1].start_ms if i + 1 < len(cues) else max(cue.end_ms, total_ms))
        for i, cue in enumerate(cues)
    ]
    return _merge_short(stretched, total_ms)


def _merge_short(cues: list[Cue], total_ms: int) -> tuple[Cue, ...]:
    """Fold any cue below ``_CUE_MIN_MS`` into the following one, so nothing flickers."""
    out: list[Cue] = []
    for cue in cues:
        if out and cue.end_ms - cue.start_ms < _CUE_MIN_MS:
            previous = out[-1]
            out[-1] = Cue(f"{previous.text} {cue.text}".strip(), previous.start_ms, cue.end_ms)
        else:
            out.append(cue)
    # Clamp to the wav we actually kept: `synthesize` clamps duration, and a cue that
    # runs past the encoded scene length would ask compose for a frame beyond the end.
    return tuple(
        Cue(cue.text, min(cue.start_ms, total_ms), min(cue.end_ms, total_ms))
        for cue in out
        if cue.start_ms < total_ms
    )


def _estimated_cues(text: str, total_ms: int) -> tuple[Cue, ...]:
    """Cues for a backend that cannot time words — `say`, or silence.

    Time is handed out in proportion to characters, which tracks speech far better
    than an equal split does: "irreversible" is not the same beat as "a".
    """
    parts = text.split()
    if not parts or total_ms <= 0:
        return ()
    weights = [len(part) + 1 for part in parts]
    total_weight = sum(weights)
    words: list[tuple[str, float, float]] = []
    elapsed = 0.0
    for part, weight in zip(parts, weights):
        span = total_ms * weight / total_weight
        words.append((part, elapsed / 1000, (elapsed + span) / 1000))
        elapsed += span
    return _group_cues(words, total_ms)


def _synth_kokoro(text: str, path: Path, voice: str, cues_out: list[Cue]) -> bool:
    """Kokoro-82M -> WAV. Returns False if the package/model is unavailable.

    Appends speech-synced cues to ``cues_out``. The word timestamps come free with
    synthesis — the pipeline already computes them to align its own vocoder — so this
    costs nothing beyond keeping the tokens instead of discarding them.
    """
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
        lang_code = voice[0] if voice else "a"
        rate = 24000
        chunks = []
        words: list[tuple[str, float, float]] = []
        with _PIPELINE_LOCK:
            pipeline = _PIPELINES.get(lang_code)
            if pipeline is None:
                pipeline = KPipeline(lang_code=lang_code)
                _PIPELINES[lang_code] = pipeline
            # Each result carries its own audio AND the token timings for that audio.
            # Offset by the audio emitted so far, because a chunk times from its own zero.
            elapsed_s = 0.0
            for result in pipeline(text, voice=voice, speed=settings.kokoro_speed):
                audio = result.audio
                words.extend(_words_from_result(result, elapsed_s))
                chunks.append(audio)
                elapsed_s += len(audio) / rate
        if not chunks:
            return False
        _write_float_wav(path, chunks, rate)
        cues_out.extend(_group_cues(words, _wav_duration_ms(path)))
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


def synthesize_timed(
    text: str, path: Path, *, backend: str | None = None, voice: str | None = None
) -> tuple[int, tuple[Cue, ...]]:
    """Speak ``text`` into ``path`` and return ``(duration_ms, cues)``.

    Never raises for a missing engine: it degrades kokoro -> say -> silence so a
    render is always producible. The duration is clamped to the schema floor and the
    per-scene ceiling. Cues are real word timings under kokoro and proportional
    estimates otherwise, so subtitles track speech on every backend.
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

    cues: list[Cue] = []
    for engine in order:
        if engine == "kokoro" and _synth_kokoro(text, path, voice, cues):
            break
        if engine == "say" and _synth_say(text, path):
            break
        if engine == "silent":
            _write_silence(path, _clamp(_estimate_ms(text)))
            break
    else:  # pragma: no cover - the "silent" branch always terminates the loop
        _write_silence(path, _clamp(_estimate_ms(text)))

    measured = _wav_duration_ms(path)
    duration = _clamp(measured if measured > 0 else _estimate_ms(text))
    # Kokoro's cues were built against the raw wav; if the clamp moved the duration,
    # they have to be rebuilt against what the scene will actually be encoded at, or
    # the last subtitle runs past the end of the scene.
    timed = _merge_short(list(cues), duration) if cues and measured == duration else ()
    return duration, timed or _estimated_cues(text, duration)


def synthesize(text: str, path: Path, *, backend: str | None = None, voice: str | None = None) -> int:
    """Speak ``text`` into ``path`` (a .wav) and return its measured duration in ms."""
    duration, _ = synthesize_timed(text, path, backend=backend, voice=voice)
    return duration


def voice_scenes(narrations: list[str], work_dir: Path, **kwargs) -> list[Voiced]:
    """Speak every scene's narration into ``work_dir`` and return the results in order."""
    work_dir.mkdir(parents=True, exist_ok=True)
    out: list[Voiced] = []
    for index, text in enumerate(narrations):
        wav = work_dir / f"scene{index}.wav"
        duration, cues = synthesize_timed(text, wav, **kwargs)
        out.append(Voiced(index=index, wav_path=wav, duration_ms=duration, cues=cues))
    return out
