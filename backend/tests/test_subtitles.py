"""Speech-synced subtitles: cue timing, and the frame timeline built from it.

The failure this guards against is silent. Subtitles that drift, overlap, or leave a
gap still render a perfectly valid MP4 — nothing raises, nothing logs, and you only
find out by watching all ninety seconds with the sound on.

    cd backend && uv run pytest -q tests/test_subtitles.py
"""

from __future__ import annotations

import pytest

# Environment isolation lives in conftest.py, imported before any test module.

from app.render import tts  # noqa: E402
from app.render.compose import _reveal_filter  # noqa: E402
from app.render.tts import _words_from_result  # noqa: E402


class _FakeToken:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.text, self.start_ts, self.end_ts = text, start, end


class _FakeResult:
    """Stands in for a kokoro `Result`, so token handling is testable without a model."""

    def __init__(self, tokens: list[tuple[str, float, float]]) -> None:
        self.tokens = [_FakeToken(*token) for token in tokens]


def cues_for(text: str, duration_ms: int) -> tuple[tts.Cue, ...]:
    """Cues without a TTS engine: the estimator every non-kokoro backend falls back to."""
    return tts._estimated_cues(text, duration_ms)


# ----------------------------------------------------------------- cue construction


def test_cues_are_gapless_and_cover_the_whole_scene() -> None:
    """A gap means a frame with no subtitle; an overlap means two at once."""
    cues = cues_for("One two three four five six seven eight nine ten eleven twelve.", 9000)
    assert cues[0].start_ms == 0
    assert cues[-1].end_ms == 9000
    for before, after in zip(cues, cues[1:]):
        assert before.end_ms == after.start_ms


def test_no_word_is_lost_or_duplicated() -> None:
    text = "Attackers flood micro amount payments with stolen card numbers across merchants."
    cues = cues_for(text, 8000)
    assert " ".join(cue.text for cue in cues) == text


def test_cues_break_at_sentence_ends() -> None:
    """A cue that straddles two sentences reads as one, and mistimes the pause."""
    cues = cues_for("First one ends here. Second one starts now.", 6000)
    assert cues[0].text == "First one ends here."


def test_cues_stay_glanceable() -> None:
    cues = cues_for(" ".join(f"word{i}" for i in range(40)), 30000)
    assert cues, "long narration produced no cues"
    for cue in cues:
        assert len(cue.text) <= tts._CUE_MAX_CHARS + len("word39") + 1


def test_short_cues_are_merged_so_nothing_flickers() -> None:
    cues = cues_for("a b c d e f g h i j k l", 1200)
    assert all(cue.end_ms - cue.start_ms >= tts._CUE_MIN_MS for cue in cues[:-1])


def test_empty_narration_produces_no_cues() -> None:
    assert cues_for("", 5000) == ()
    assert cues_for("anything", 0) == ()


def test_hyphenated_service_names_survive_tokenisation() -> None:
    """Kokoro splits "payments-upi" into three tokens. Gluing the hyphen backwards and
    then starting a fresh word rendered it "payments- upi" — a service name broken in
    half, in a video whose entire claim is that the names are exact."""
    words = _words_from_result(
        _FakeResult(
            [
                ("It", 0.0, 0.2),
                ("reaches", 0.2, 0.6),
                ("payments", 0.6, 1.1),
                ("-", 1.1, 1.15),
                ("upi", 1.15, 1.5),
                (".", 1.5, 1.6),
            ]
        ),
        0.0,
    )
    assert [word for word, _, _ in words] == ["It", "reaches", "payments-upi."]


def test_sentences_are_not_run_together() -> None:
    """The counterpart risk: treating "." as a connector too would glue "here.Next"."""
    words = _words_from_result(
        _FakeResult([("here", 0.0, 0.4), (".", 0.4, 0.6), ("Next", 0.6, 1.0)]), 0.0
    )
    assert [word for word, _, _ in words] == ["here.", "Next"]


def test_chunk_offsets_are_applied() -> None:
    """Kokoro times each chunk from its own zero, so a multi-chunk narration would
    restart its subtitles partway through the scene."""
    words = _words_from_result(_FakeResult([("late", 0.0, 0.5)]), offset_s=4.0)
    assert words == [("late", 4.0, 4.5)]


# ------------------------------------------------------------------- the ffmpeg side


def test_subtitles_cut_rather_than_fade() -> None:
    """The defect this exists for: cross-faded subtitles showed the outgoing and
    incoming line at once, both legible, and dimmed the frame under them. Plates must
    be gated with `enable`, never with `fade`."""
    chain = _reveal_filter(
        1080, 1920, 30, frame_s=[5.0], footage=False, caption_windows=[(0.0, 2.0), (2.0, 5.0)]
    )
    plates = [part for part in chain.split(";") if "cp" in part and "overlay" in part]
    assert len(plates) == 2
    for part in plates:
        assert "enable='between(t" in part
        assert "fade" not in part


def test_subtitle_windows_are_placed_where_the_words_are() -> None:
    chain = _reveal_filter(
        1080, 1920, 30, frame_s=[9.0], footage=False, caption_windows=[(0.0, 3.125), (3.125, 9.0)]
    )
    assert "between(t\\,0.000\\,3.125)" in chain
    assert "between(t\\,3.125\\,9.000)" in chain


def test_subtitle_plate_inputs_start_after_the_content_frames() -> None:
    """Input indices are positional in the ffmpeg command. Off by one here composites
    a build-up frame as a subtitle and drops the real one."""
    chain = _reveal_filter(
        1080, 1920, 30, frame_s=[2.0, 2.0, 2.0], footage=False, caption_windows=[(0.0, 6.0)]
    )
    for content_index in (1, 2, 3):
        assert f"[{content_index}:v]" in chain
    assert "[4:v]" in chain  # the first caption plate, after 3 content frames
    assert "[5:v]" not in chain


def test_commas_inside_enable_are_escaped() -> None:
    """Unescaped, ffmpeg reads them as filter argument separators and rejects the
    whole graph — and this string is passed without a shell, so quoting will not do it."""
    chain = _reveal_filter(
        1080, 1920, 30, frame_s=[4.0], footage=False, caption_windows=[(0.0, 4.0)]
    )
    enable = chain.split("enable=")[1]
    assert "between(t\\," in enable
    assert "between(t," not in enable


def test_content_still_cross_fades() -> None:
    """The subtitle change must not cost the build-up its cross-fade: a bullet should
    still arrive rather than pop."""
    chain = _reveal_filter(
        1080, 1920, 30, frame_s=[2.0, 2.0], footage=False, caption_windows=[(0.0, 4.0)]
    )
    assert "fade=t=in" in chain
    assert "fade=t=out" in chain


def test_reveal_filter_never_overlaps_two_fades_on_one_frame() -> None:
    """A fade pair that overlaps on one stream makes ffmpeg render it wrong rather
    than fail, so this is only ever caught by looking."""
    frame_s = [0.4, 3.0, 0.3, 2.0]
    chain = _reveal_filter(1080, 1920, 30, frame_s=frame_s, footage=False)
    for index, span in enumerate(frame_s):
        for part in chain.split(";"):
            if not part.startswith(f"[{index + 1}:v]"):
                continue
            durations = [
                float(piece.split(":d=")[1].split(":")[0])
                for piece in part.split("fade=")[1:]
            ]
            assert all(d <= span / 2 + 1e-9 for d in durations), part


@pytest.mark.parametrize("count", [1, 2, 6])
def test_reveal_filter_wires_every_frame_to_the_output(count: int) -> None:
    chain = _reveal_filter(1080, 1920, 30, frame_s=[2.0] * count, footage=True)
    for index in range(count):
        assert f"[{index + 1}:v]" in chain
    assert chain.rstrip().endswith("[v]")


@pytest.mark.parametrize("captions", [0, 1, 4])
def test_chain_always_ends_in_the_output_label(captions: int) -> None:
    """With or without subtitles, exactly one stream may be labelled [v]."""
    windows = [(float(i), float(i + 1)) for i in range(captions)]
    chain = _reveal_filter(1080, 1920, 30, frame_s=[4.0, 4.0], footage=False, caption_windows=windows)
    assert chain.rstrip().endswith("[v]")
    assert chain.count("[v];") + chain.count("[v]") == 1


# ------------------------------------------------------ the subtitle covers nothing


def test_subtitle_never_covers_scene_content() -> None:
    """The subtitle is absolutely positioned, so it is outside the flow and cannot
    push anything aside — the reserved band in the body's bottom padding is the only
    thing keeping it off a diagram. Measured in a real browser because that band is
    computed from four CSS variables, and getting any of them wrong prints text over
    the architecture rather than raising anything.
    """
    import json
    from pathlib import Path

    playwright = pytest.importorskip("playwright.sync_api")
    from app.render import html
    from app.storyboard import validate_storyboard

    fixture = (
        Path(__file__).resolve().parents[2] / "src" / "lib" / "fixtures" / "otm-rearch.storyboard.json"
    )
    storyboard = validate_storyboard(json.loads(fixture.read_text()), stage="script")
    # A cue at the character cap, which is the widest a subtitle is allowed to get.
    widest = "x" * tts._CUE_MAX_CHARS

    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--allow-file-access-from-files"])
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        try:
            for index, scene in enumerate(storyboard.scenes):
                document = html.scene_html(scene, width=1080, height=1920, caption=widest)
                page.set_content(document)
                try:
                    page.wait_for_function("window.__ready === true", timeout=15_000)
                except Exception:
                    pass  # a diagram that did not settle still has a laid-out block
                box = page.evaluate(
                    "() => {"
                    " const c = document.querySelector('.caption').getBoundingClientRect();"
                    " const b = document.querySelector('.block').getBoundingClientRect();"
                    " return {caption_top: c.top, content_bottom: b.bottom, caption_height: c.height};"
                    "}"
                )
                assert box["content_bottom"] <= box["caption_top"], (
                    f"scene {index} ({scene.type}): content reaches "
                    f"{box['content_bottom']:.0f}px, subtitle starts at {box['caption_top']:.0f}px"
                )
        finally:
            browser.close()
