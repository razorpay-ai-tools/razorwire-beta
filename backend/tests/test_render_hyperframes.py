"""Tests for the HyperFrames render engine.

Composition emission is pure and needs no browser, so the timing contract is checked
here without rendering anything. The contract is the reason this engine exists in the
first place: the picture and the voice share one clock, and a scene starts exactly
where the previous scene's narration ended.
"""

from __future__ import annotations

import re
import wave
from pathlib import Path

import pytest

from app.render import hyperframes
from app.render.tts import Cue, Voiced
from app.storyboard import validate_storyboard

_STORYBOARD = {
    "meta": {"title": "Engine Test Reel", "tags": ["test"]},
    "source": {"kind": "topic"},
    "scenes": [
        {
            "type": "title",
            "heading": "Hello",
            "sub": "A subtitle",
            "narration": "One sentence of narration for the title scene.",
        },
        {
            "type": "bullets",
            "heading": "Two points",
            "bullets": ["First point", "Second point"],
            "narration": "Two short points to consider here.",
            "cite": "Section 2 - Points",
        },
        {
            "type": "diagram",
            "heading": "The flow",
            "mermaid": "graph TD\n  A[Edge] --> B[Router]\n  B --> C[Store]",
            "narration": "A request enters at Edge and reaches the store.",
            "cite": "Section 4.1 - Request Flow",
        },
        {
            "type": "outro",
            "cta": "Read the full spec",
            "narration": "The full spec has the rest of the detail.",
        },
    ],
}


def _wav(path: Path, ms: int) -> Path:
    """A real, readable wav of a known length — the engine copies these files."""
    rate = 22050
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * ms / 1000))
    return path


@pytest.fixture
def built(tmp_path: Path):
    sb = validate_storyboard(_STORYBOARD, stage="script")
    durations = [2000, 3500, 4000, 2500]
    voiced = [
        Voiced(
            index=i,
            wav_path=_wav(tmp_path / f"v{i}.wav", ms),
            duration_ms=ms,
            cues=(Cue("first line", 0, ms // 2), Cue("second line", ms // 2, ms)),
        )
        for i, ms in enumerate(durations)
    ]
    project = hyperframes.build_composition(sb, voiced, tmp_path / "composition")
    return (project / "index.html").read_text(), durations


def _attrs(html: str, element_id: str) -> tuple[float, float]:
    """(data-start, data-duration) for one element."""
    match = re.search(
        rf'id="{re.escape(element_id)}"[^>]*?data-start="([\d.]+)"[^>]*?data-duration="([\d.]+)"',
        html,
    )
    assert match, f"no timed element with id {element_id!r}"
    return float(match.group(1)), float(match.group(2))


def test_scene_starts_are_the_running_sum_of_narration(built):
    """The anti-desync rule. A scene begins where the previous voice stopped — if this
    drifts, every scene after it is describing the wrong picture."""
    html, durations = built
    expected = 0.0
    for index, ms in enumerate(durations):
        start, duration = _attrs(html, f"s{index}")
        assert start == pytest.approx(expected, abs=0.002)
        assert duration == pytest.approx(ms / 1000, abs=0.002)
        expected += ms / 1000

    root = re.search(r'data-composition-id="main"[^>]*data-duration="([\d.]+)"', html)
    assert root and float(root.group(1)) == pytest.approx(sum(durations) / 1000, abs=0.002)


def test_every_caption_stays_inside_its_own_scene(built):
    """A caption clip is absolutely timed, so a cue that overran its scene would hang
    over the next one's picture — the one desync a viewer actually notices."""
    html, durations = built
    elapsed = 0.0
    for index, ms in enumerate(durations):
        scene_end = elapsed + ms / 1000
        for position in range(2):
            start, duration = _attrs(html, f"s{index}-cap{position}")
            assert start >= elapsed - 0.002
            assert start + duration <= scene_end + 0.002
        elapsed = scene_end


def test_narration_and_citations_survive_into_the_composition(built):
    html, _ = built
    assert "Section 4.1 - Request Flow" in html
    assert "first line" in html and "second line" in html
    # One narration track per scene, each addressable by the mixer.
    assert html.count('<audio id="vo') == 4


def test_diagram_nodes_are_revealed_by_opacity_only(built):
    """Mermaid positions each node with its own transform; a GSAP x/y tween rewrites
    that attribute and stacks every node at the SVG origin."""
    html, _ = built
    build_fn = html.split("function buildDiagram")[1].split("function build(")[0]
    reveal = build_fn.split("nodes.forEach")[1]
    assert "opacity" in reveal
    assert " y:" not in reveal and " x:" not in reveal


def test_edge_arrowheads_are_stripped_at_build_not_at_draw_time(built):
    """A marker paints at the path's geometric end however little stroke is visible.

    Scheduling the removal for the moment the draw starts left every not-yet-drawn
    edge showing a disembodied arrowhead floating above its own line, which looked
    like a rendering fault. It has to come off synchronously, when the diagram is
    wired, and go back on only once the stroke has arrived.
    """
    html, _ = built
    draw = html.split("function drawEdge")[1].split("\n    }")[0]

    # Removed by touching the element, not by a timeline `set` at the draw's start.
    assert 'edge.setAttribute("marker-end", "none")' in draw
    assert 'tl.set(edge, { attr: { "marker-end": "none" } }' not in draw
    # Restored only after the stroke has finished drawing.
    assert 'tl.set(edge, { attr: { "marker-end": marker } }, at + DRAW)' in draw
    assert 'drawSVG: "0%"' in draw and 'drawSVG: "100%"' in draw


def test_missing_gsap_plugins_degrade_rather_than_fail(built):
    """A plugin that failed to copy should cost polish, never the scene."""
    html, _ = built
    assert 'typeof SplitText === "undefined"' in html
    assert 'typeof DrawSVGPlugin !== "undefined"' in html


def test_a_missing_node_toolchain_falls_back_to_ffmpeg(monkeypatch, tmp_path: Path):
    """The composition engine is the default, but a deploy image may not carry Node.

    A reel with plainer motion beats a job that fails because Chrome's sibling is not
    installed, so `RenderUnavailable` — and only that — drops to the ffmpeg path.
    """
    from app.render import hyperframes as hf, pipeline as pl
    from app.render.errors import RenderUnavailable

    monkeypatch.setattr(pl.settings, "render_engine", "hyperframes")
    monkeypatch.setattr(pl.settings, "render_qa", False)

    def no_node(*_args, **_kwargs):
        raise RenderUnavailable("npx is not on PATH (install Node.js 22+)")

    monkeypatch.setattr(hf, "render_from_voiced", no_node)

    called: dict[str, bool] = {}

    def fake_ffmpeg(sb, voiced, work_dir):
        called["ffmpeg"] = True
        return pl.RenderResult(mp4_path=tmp_path / "v.mp4", duration_ms=1000, scene_durations=[1000])

    monkeypatch.setattr(pl, "_render_with_ffmpeg", fake_ffmpeg)

    result = pl.render_from_voiced(object(), [], tmp_path)
    assert called.get("ffmpeg") is True
    assert result.duration_ms == 1000


def test_a_broken_composition_still_fails_loudly(monkeypatch, tmp_path: Path):
    """A composition that fails `check` or `render` is our bug, not a missing tool.
    Downgrading it to ffmpeg would publish a lesser reel and hide the defect."""
    from app.render import hyperframes as hf, pipeline as pl

    monkeypatch.setattr(pl.settings, "render_engine", "hyperframes")

    def broken(*_args, **_kwargs):
        raise RuntimeError("hyperframes check failed: gsap_css_transform_conflict")

    monkeypatch.setattr(hf, "render_from_voiced", broken)
    monkeypatch.setattr(
        pl, "_render_with_ffmpeg",
        lambda *a, **k: pytest.fail("must not fall back on a composition defect"),
    )

    with pytest.raises(RuntimeError, match="check failed"):
        pl.render_from_voiced(object(), [], tmp_path)


def test_two_diagrams_under_a_frozen_clock_each_draw_into_their_own_svg(tmp_path: Path):
    """The renderer freezes ``Date.now()`` for determinism, and mermaid names each
    diagram ``mermaid-<Date.now()>``. Two diagrams then shared one id, and the second
    drew into the first's SVG: the "current" and "fixed" architectures piled on top of
    each other in one scene while the next scene's diagram stayed empty."""
    playwright = pytest.importorskip("playwright.sync_api")
    board = dict(_STORYBOARD)
    second = {
        "type": "diagram",
        "heading": "The fixed flow",
        "mermaid": "graph TD\n  X[Queue] --> Y[Worker]\n  Y -->|acks| Z[Store]",
        "narration": "Now a queue feeds the worker.",
        "cite": "Section 5 - Fix",
    }
    board["scenes"] = [*_STORYBOARD["scenes"][:3], second, _STORYBOARD["scenes"][3]]
    sb = validate_storyboard(board, stage="script")
    voiced = [
        Voiced(index=i, wav_path=_wav(tmp_path / f"v{i}.wav", 1500), duration_ms=1500, cues=())
        for i in range(len(sb.scenes))
    ]
    project = hyperframes.build_composition(sb, voiced, tmp_path / "composition")
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except playwright.Error as exc:  # no Chromium on this box
            pytest.skip(f"chromium unavailable: {exc}")
        page = browser.new_page()
        page.add_init_script("window.__timelines = {}; Date.now = () => 1790000000000;")
        page.goto((project / "index.html").as_uri(), wait_until="domcontentloaded")
        # Polled from Python: Playwright's own wait_for_function times itself with the
        # very Date.now this test freezes, and never fires.
        for _ in range(150):
            if page.evaluate("() => !!window.__timelines.main"):
                break
            page.wait_for_timeout(100)
        labels = page.evaluate(
            """() => ["s2", "s3"].map(sid => [...document.querySelectorAll(
                 "#" + sid + "-d svg .node")].map(n => n.textContent.trim()))"""
        )
        # At t=0 no edge has been drawn, so no edge label may show yet. Mermaid nests a
        # second `.edgeLabel` span inside each label group; indexing the flat list paired
        # label j with the wrong edge and left real labels visible from frame one.
        shown = page.evaluate(
            """() => [...document.querySelectorAll("#s3-d svg .edgeLabels > .edgeLabel")]
                 .filter(g => g.textContent.trim() && getComputedStyle(g).opacity !== "0")
                 .map(g => g.textContent.trim())"""
        )
        browser.close()
    assert labels == [["Edge", "Router", "Store"], ["Queue", "Worker", "Store"]]
    assert shown == []


def test_interactive_copy_carries_its_own_runtime(monkeypatch, tmp_path: Path):
    """The feed's player falls back to a CDN runtime when the page lacks one; the
    published copy bakes the vendored one in, and the render copy stays untouched."""
    monkeypatch.setattr(hyperframes.settings, "media_dir", str(tmp_path / "media"))
    monkeypatch.setattr(type(hyperframes.settings), "supabase_storage_enabled", property(lambda s: False))
    sb = validate_storyboard({**_STORYBOARD, "meta": {**_STORYBOARD["meta"], "theme": "launch"}}, stage="script")
    voiced = [
        Voiced(index=i, wav_path=_wav(tmp_path / f"v{i}.wav", 1200), duration_ms=1200, cues=())
        for i in range(len(sb.scenes))
    ]
    url = hyperframes.publish_interactive(sb, voiced, "job1")
    assert url == "/media/job1_hf/play.html"
    project = tmp_path / "media" / "job1_hf"
    play = (project / "play.html").read_text()
    assert '<script src="assets/hyperframe.runtime.iife.js"></script>' in play
    assert (project / "assets" / "hyperframe.runtime.iife.js").is_file()
    assert "hyperframe.runtime" not in (project / "index.html").read_text()
    assert "--accent:#c6ff3d" in play  # the launch theme reached the page
