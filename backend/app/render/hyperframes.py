"""Internal storyboard + voiced narration -> one HyperFrames composition -> MP4.

An alternative to the ``capture`` + ``compose`` pair, selected with
``settings.render_engine``. Same inputs, same output contract (``RenderResult``),
same anti-desync rule: **scene length is the measured length of its narration wav**,
never a number the model picked.

Why a second engine at all. The ffmpeg path encodes each scene as a still (or a
short stack of stills) and joins them with ``xfade``, so everything that reads as
motion has to be faked with cross-faded screenshots, and the join arithmetic in
``compose._join_filter`` exists only to keep those overlaps from dragging the audio
out of step. Two consequences are visible in the output:

  * ``SCENE_TRANSITION`` had to be ``fadeblack`` rather than a dissolve, because two
    consecutive scenes put their heading and caption in the same two places and a
    cross-dissolve showed both texts at once.
  * subtitles needed a whole second capture pass on a transparent plate
    (``html.__layer``) so they could hard-cut over content that was still fading.

In a composition both problems stop existing rather than getting solved: a scene's
elements animate individually, so nothing is ever a cross-fade between two full
frames, and a subtitle is its own timed clip, so a cut is the default.

What this file deliberately does NOT change:

  * the storyboard contract and its validators,
  * the citation chip on every scene,
  * the Mermaid diagram — still drawn by the real library, still built up node by
    node with an edge appearing only once both its endpoints have,
  * the cue splitting in ``tts``.

Rendering shells out to the HyperFrames CLI, which brings its own Chrome. Nothing
leaves the box: the local ``render`` path is used, never ``cloud render``, because
these frames are derived from internal documents.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config import settings
from .errors import RenderUnavailable
from .html import MERMAID_JS, _esc

log = logging.getLogger(__name__)

#: GSAP and the two plugins this engine uses, vendored out of ``node_modules`` beside
#: mermaid rather than pulled from a CDN at render time. A render that needs the
#: network to draw a diagram is a render that fails on a bad day for no good reason.
#:
#: DrawSVGPlugin and SplitText were Club-only until GSAP 3.13, when Webflow made the
#: whole library free including commercial use. They ship in the public npm package
#: now, so this is a plain dependency rather than a licence question.
_GSAP_DIR = MERMAID_JS.parents[2] / "gsap" / "dist"
GSAP_JS = _GSAP_DIR / "gsap.min.js"
DRAWSVG_JS = _GSAP_DIR / "DrawSVGPlugin.min.js"
SPLITTEXT_JS = _GSAP_DIR / "SplitText.min.js"

#: The HyperFrames runtime, for the copy of a composition the feed's player plays. The
#: CLI injects its own when rendering; the player would fetch this same file from a CDN
#: if the page lacked it, so it is vendored, pinned with ``CLI``, and baked in instead.
RUNTIME_JS = MERMAID_JS.parents[2] / "@hyperframes" / "core" / "dist" / "hyperframe.runtime.iife.js"

#: Pinned so a reel re-renders identically months later.
CLI = "hyperframes@0.8.47"

#: How long a scene's own content takes to arrive, and the slice of the scene it is
#: allowed to spend arriving. A build-up that ran the whole scene would still be
#: moving while the narration had moved on.
ENTRANCE_S = 0.42
BUILD_FRACTION = 0.55

#: Music bed level. Well under the narration, which is the point of the reel.
BED_VOLUME = 0.12

_SUBPROCESS_TIMEOUT = 900


#: One look + one motion per ``meta.theme``. Every reel used to be the same navy
#: gradient, the same rise-and-fade and the same type, so a launch and an RCA came out as
#: the same video. ``css`` fills the custom properties ``_STYLE`` reads; ``mermaid`` is
#: literal hex because mermaid inlines it into the SVG; ``enter``/``leave`` are the GSAP
#: vars every entrance and exit uses, so a theme changes how the whole reel moves.
THEMES: dict[str, dict[str, Any]] = {
    "explainer": {
        "css": {
            "--bg-a": "#0b1020", "--bg-b": "#241a4a", "--bg-c": "#0f2a4a",
            "--ink": "#f8fafc", "--muted": "#cbd5e1", "--accent": "#60a5fa",
            "--accent-2": "#a78bfa", "--panel": "rgba(15,23,42,.55)",
            "--line": "rgba(148,163,184,.3)", "--head-font": "var(--sans)",
            "--head-weight": "750", "--head-case": "none", "--title-size": "96px",
            "--grid": "none, none",
        },
        "mermaid": {"primaryColor": "#16213d", "primaryBorderColor": "#60a5fa",
                    "primaryTextColor": "#f8fafc", "lineColor": "#93c5fd",
                    "edgeLabelBackground": "#0b1020"},
        "enter": {"opacity": 0, "y": 28},
        "ease": "power3.out", "stagger": 0.055,
        "leave": {"opacity": 0, "y": -36, "ease": "power2.in"},
        "words": {"yPercent": 115, "opacity": 0},
        "wipe": False,
    },
    "launch": {
        "css": {
            "--bg-a": "#050505", "--bg-b": "#1a0b2e", "--bg-c": "#0a1f14",
            "--ink": "#ffffff", "--muted": "#d4d4d8", "--accent": "#c6ff3d",
            "--accent-2": "#ff3dac", "--panel": "rgba(255,255,255,.06)",
            "--line": "rgba(198,255,61,.35)", "--head-font": "var(--sans)",
            "--head-weight": "900", "--head-case": "uppercase", "--title-size": "124px",
            "--grid": "none, none",
        },
        "mermaid": {"primaryColor": "#111111", "primaryBorderColor": "#c6ff3d",
                    "primaryTextColor": "#ffffff", "lineColor": "#c6ff3d",
                    "edgeLabelBackground": "#050505"},
        "enter": {"opacity": 0, "scale": 0.82, "y": 18},
        "ease": "back.out(1.8)", "stagger": 0.04,
        "leave": {"opacity": 0, "scale": 1.08, "ease": "power2.in"},
        "words": {"yPercent": 70, "scale": 0.6, "opacity": 0},
        "wipe": True,
    },
    "incident": {
        "css": {
            "--bg-a": "#0c0a0a", "--bg-b": "#2a0f12", "--bg-c": "#1a1410",
            "--ink": "#f5f5f4", "--muted": "#d6d3d1", "--accent": "#f59e0b",
            "--accent-2": "#ef4444", "--panel": "rgba(28,25,23,.7)",
            "--line": "rgba(245,158,11,.3)", "--head-font": "var(--mono)",
            "--head-weight": "700", "--head-case": "none", "--title-size": "84px",
            "--grid": "none, none",
        },
        "mermaid": {"primaryColor": "#1c1917", "primaryBorderColor": "#f59e0b",
                    "primaryTextColor": "#f5f5f4", "lineColor": "#f59e0b",
                    "edgeLabelBackground": "#0c0a0a"},
        "enter": {"opacity": 0},
        "ease": "sine.out", "stagger": 0.08,
        "leave": {"opacity": 0, "ease": "sine.in"},
        "words": {"opacity": 0},
        "wipe": False,
    },
    "blueprint": {
        "css": {
            "--bg-a": "#061426", "--bg-b": "#0a2342", "--bg-c": "#071b33",
            "--ink": "#e0f2fe", "--muted": "#bae6fd", "--accent": "#22d3ee",
            "--accent-2": "#38bdf8", "--panel": "rgba(8,47,73,.55)",
            "--line": "rgba(34,211,238,.35)", "--head-font": "var(--mono)",
            "--head-weight": "650", "--head-case": "none", "--title-size": "88px",
            "--grid": ("linear-gradient(rgba(56,189,248,.08) 1px, transparent 1px), "
                       "linear-gradient(90deg, rgba(56,189,248,.08) 1px, transparent 1px)"),
        },
        "mermaid": {"primaryColor": "#082f49", "primaryBorderColor": "#22d3ee",
                    "primaryTextColor": "#e0f2fe", "lineColor": "#38bdf8",
                    "edgeLabelBackground": "#061426"},
        "enter": {"opacity": 0, "x": -40},
        "ease": "expo.out", "stagger": 0.05,
        "leave": {"opacity": 0, "x": 60, "ease": "power2.in"},
        "words": {"x": -30, "opacity": 0},
        "wipe": False,
    },
}
_DEFAULT_THEME = "explainer"

#: How long a scene's content spends leaving before the next scene's arrives.
LEAVE_S = 0.32


def _theme(sb: Any) -> dict[str, Any]:
    name = getattr(getattr(getattr(sb, "meta", None), "theme", None), "value", None)
    return THEMES.get(name or _DEFAULT_THEME, THEMES[_DEFAULT_THEME])


# --------------------------------------------------------------------------- markup


def _content(scene: Any, sid: str) -> str:
    """One scene's visual. Every animatable part carries an id so the timeline can
    address it; nothing carries a CSS transform, which would fight the tween."""
    kind = scene.type
    if kind == "title":
        sub = getattr(scene, "sub", None)
        return (
            f'<div class="block center" id="{sid}-block">'
            f'<h1 class="title" id="{sid}-h">{_esc(scene.heading)}</h1>'
            + (f'<p class="sub" id="{sid}-s">{_esc(sub)}</p>' if sub else "")
            + "</div>"
        )
    if kind == "bullets":
        items = "".join(
            f'<li id="{sid}-b{i}">{_esc(item)}</li>' for i, item in enumerate(scene.bullets)
        )
        return (
            f'<div class="block" id="{sid}-block">'
            f'<h2 class="heading" id="{sid}-h">{_esc(scene.heading)}</h2>'
            f'<ul class="bullets">{items}</ul>'
            "</div>"
        )
    if kind == "diagram":
        return (
            f'<div class="block" id="{sid}-block">'
            f'<h2 class="heading" id="{sid}-h">{_esc(scene.heading)}</h2>'
            f'<div class="diagram" id="{sid}-d"><pre class="mermaid">{_esc(scene.mermaid)}</pre></div>'
            "</div>"
        )
    if kind == "compare":
        return (
            f'<div class="block" id="{sid}-block">'
            f'<h2 class="heading" id="{sid}-h">{_esc(scene.heading)}</h2>'
            '<div class="compare">'
            f'{_pane(scene.left, f"{sid}-l")}{_pane(scene.right, f"{sid}-r")}'
            "</div></div>"
        )
    if kind == "code":
        heading = getattr(scene, "heading", None)
        return (
            f'<div class="block" id="{sid}-block">'
            + (f'<h2 class="heading" id="{sid}-h">{_esc(heading)}</h2>' if heading else "")
            + f'<pre class="code" id="{sid}-c"><code>{_esc(scene.code)}</code></pre></div>'
        )
    if kind == "outro":
        url = getattr(scene, "url", None)
        return (
            f'<div class="block center" id="{sid}-block">'
            f'<div class="outro-cta" id="{sid}-h">{_esc(scene.cta)}</div>'
            + (f'<div class="outro-url" id="{sid}-s">{_esc(url)}</div>' if url else "")
            + "</div>"
        )
    return f'<div class="block center" id="{sid}-block"><p class="sub">{_esc(kind)}</p></div>'


def _pane(pane: Any, pid: str) -> str:
    items = "".join(f"<li>{_esc(item)}</li>" for item in pane.items)
    return (
        f'<div class="pane" id="{pid}">'
        f'<div class="pane-label">{_esc(pane.label)}</div>'
        f"<ul>{items}</ul></div>"
    )


def _scene_section(scene: Any, index: int, start_s: float, dur_s: float) -> str:
    sid = f"s{index}"
    cite = getattr(scene, "cite", None)
    chip = (
        f'<div class="cite" id="{sid}-cite">{_esc(cite)}</div>' if cite else ""
    )
    return (
        f'<section class="clip scene" id="{sid}" data-start="{start_s:.3f}" '
        f'data-duration="{dur_s:.3f}" data-track-index="{index}">'
        f"{chip}{_content(scene, sid)}"
        "</section>"
    )


def _caption_clips(
    cues: Any, narration: str, index: int, start_s: float, dur_s: float
) -> str:
    """One timed clip per subtitle cue.

    The cue's own window becomes the clip's window, so a subtitle CUTS to the next
    one by construction — which is the whole reason the ffmpeg path needed a second
    alpha capture pass. A scene whose backend could not time words falls back to one
    clip carrying the entire narration, exactly as ``html._caption`` does.
    """
    if not cues:
        text = _esc(narration or "")
        if not text:
            return ""
        return (
            f'<p class="caption clip" id="s{index}-cap0" data-start="{start_s:.3f}" '
            f'data-duration="{dur_s:.3f}" data-track-index="20">{text}</p>'
        )
    out = []
    for position, cue in enumerate(cues):
        cue_start = start_s + cue.start_ms / 1000
        cue_dur = max(0.1, (cue.end_ms - cue.start_ms) / 1000)
        # Never let the last cue outlive its scene: the clip window is half-open, and
        # a caption hanging into the next scene is the one desync a viewer notices.
        cue_dur = min(cue_dur, start_s + dur_s - cue_start)
        if cue_dur <= 0:
            continue
        out.append(
            f'<p class="caption clip" id="s{index}-cap{position}" '
            f'data-start="{cue_start:.3f}" data-duration="{cue_dur:.3f}" '
            f'data-track-index="20">{_esc(cue.text)}</p>'
        )
    return "".join(out)


# ------------------------------------------------------------------------- timeline


def _scene_timeline(
    scene: Any, index: int, start_s: float, dur_s: float, *, last: bool = False
) -> str:
    """GSAP for one scene: entrances in the theme's motion, then an exit.

    The exit is what makes a cut read as a transition. Content used to be yanked at the
    clip boundary while the next scene faded in from black; now it leaves in its own
    last ``LEAVE_S`` over the background layer that never goes away, and the next scene
    arrives onto that same background. The last scene holds to the end instead.
    """
    sid = f"s{index}"
    build = max(0.6, dur_s * BUILD_FRACTION)
    js: list[str] = []
    if getattr(scene, "cite", None):
        js.append(f'enter("#{sid}-cite", {start_s + 0.12:.3f});')
    # Headings arrive a word at a time. `riseWords` falls back to the whole element
    # when SplitText is unavailable, so the scene still animates.
    js.append(f'riseWords("#{sid}-h", {start_s + 0.08:.3f});')

    kind = scene.type
    if kind in ("title", "outro"):
        js.append(f'enter("#{sid}-s", {start_s + 0.42:.3f});')
    elif kind == "bullets":
        count = len(scene.bullets)
        step = build / max(count, 1)
        for i in range(count):
            js.append(f'enter("#{sid}-b{i}", {start_s + 0.45 + i * step:.3f});')
    elif kind == "compare":
        js.append(f'enter("#{sid}-l", {start_s + 0.45:.3f});')
        js.append(f'enter("#{sid}-r", {start_s + 0.62:.3f});')
    elif kind == "code":
        js.append(f'enter("#{sid}-c", {start_s + 0.4:.3f});')
    elif kind == "diagram":
        # Node-by-node, timed from the timeline rather than from a screenshot loop.
        js.append(f'buildDiagram("{sid}", {start_s + 0.5:.3f}, {build:.3f});')
    if not last and dur_s > LEAVE_S * 3:
        js.append(f'leave("{sid}", {start_s + dur_s - LEAVE_S:.3f});')
    return "\n      ".join(js)


def _stage_timeline(starts: list[float], theme: dict[str, Any]) -> str:
    """The background layer and the between-scene wipes: the parts that outlive a scene.

    The background eases to a new focus at every cut, so even a plain cut moves.
    """
    js = ['tl.fromTo("#bgplate", {opacity:0}, {opacity:1, duration:0.5, ease:"power2.out"}, 0);']
    for i, at in enumerate(starts[1:], start=1):
        x, y = (i * 37) % 100, (i * 61) % 100
        js.append(
            f'tl.to("#bgplate", {{backgroundPosition:"{x}% {y}%", duration:{LEAVE_S * 2:.2f}, '
            f'ease:"sine.inOut"}}, {max(0.0, at - LEAVE_S):.3f});'
        )
        if theme["wipe"]:
            js.append(
                f'tl.fromTo("#w{i}-bar", {{xPercent:-101}}, {{xPercent:101, duration:0.6, '
                f'ease:"power3.inOut"}}, {max(0.0, at - 0.3):.3f});'
            )
    return "\n      ".join(js)


def _wipes(starts: list[float], theme: dict[str, Any]) -> str:
    if not theme["wipe"]:
        return ""
    return "".join(
        f'<div class="clip wipe" id="w{i}" data-start="{max(0.0, at - 0.3):.3f}" '
        f'data-duration="0.600" data-track-index="24"><div class="wipe-bar" id="w{i}-bar"></div></div>'
        for i, at in enumerate(starts[1:], start=1)
    )


#: Ported from ``html._REVEAL_JS``. Same rule, different consumer: there it drove a
#: screenshot per step, here it hands the timeline a list of elements to fade in.
#: Mermaid v11 encodes an edge's endpoints in its id as ``<prefix>-L_A_B_0``, and a
#: node name may itself contain underscores, so every split is tried until both
#: halves name known nodes.
_DIAGRAM_JS = """
    /**
     * A heading arriving one word at a time, masked so each word slides out from
     * behind its own line rather than floating up through the frame.
     *
     * SplitText is the GSAP plugin that was Club-only before 3.13. If it is missing
     * for any reason the heading still animates, as one block — a missing plugin
     * should cost polish, never the scene.
     */
    var REST = { opacity: 1, x: 0, y: 0, xPercent: 0, yPercent: 0, scale: 1 };
    function settle(from) {
      var to = {};
      Object.keys(from).forEach(function (k) { to[k] = REST[k]; });
      return to;
    }

    /** One element arriving in the theme's motion. A missing element is a no-op. */
    function enter(selector, at) {
      var el = document.querySelector(selector);
      if (!el) return;
      tl.fromTo(el, Object.assign({}, MOTION.enter),
        Object.assign(settle(MOTION.enter), { duration: 0.46, ease: MOTION.ease }), at);
    }

    /** A scene's content leaving before the next scene arrives. */
    function leave(sid, at) {
      var els = ["#" + sid + "-block", "#" + sid + "-cite"]
        .map(function (s) { return document.querySelector(s); }).filter(Boolean);
      if (!els.length) return;
      tl.to(els, Object.assign({}, MOTION.leave, { duration: LEAVE_S }), at);
    }

    function riseWords(selector, at) {
      var el = document.querySelector(selector);
      if (!el) return;
      if (typeof SplitText === "undefined") { enter(selector, at); return; }
      var masked = MOTION.words.yPercent !== undefined;
      var split = new SplitText(el, masked ? { type: "words,lines", mask: "lines" }
                                           : { type: "words" });
      tl.fromTo(split.words, Object.assign({}, MOTION.words),
        Object.assign(settle(MOTION.words),
          { duration: 0.5, ease: MOTION.ease, stagger: MOTION.stagger }), at);
    }

    function buildDiagram(sid, at, span) {
      var svg = document.querySelector("#" + sid + "-d svg");
      if (!svg) return;
      var nodes = Array.prototype.slice.call(svg.querySelectorAll(".node"));
      if (nodes.length < 2) {
        tl.fromTo("#" + sid + "-d", { opacity: 0 }, { opacity: 1, duration: 0.4 }, at);
        return;
      }
      var ids = nodes.map(function (n) {
        var m = n.id.match(/flowchart-(.+)-\\d+$/);
        return m ? m[1] : null;
      });
      var known = {};
      ids.forEach(function (id) { if (id) known[id] = true; });
      var edges = Array.prototype.slice.call(svg.querySelectorAll(".flowchart-link"));
      // Direct children only: mermaid nests a second `.edgeLabel` span inside each label
      // group, so the flat list is twice as long as the edge list and label j belongs to
      // some other edge.
      var labels = Array.prototype.slice.call(svg.querySelectorAll(".edgeLabels > .edgeLabel"));
      var endpoints = edges.map(function (e) {
        var m = e.id.match(/-L_(.+)_\\d+$/);
        if (!m) return null;
        for (var cut = 1; cut < m[1].length - 1; cut++) {
          if (m[1][cut] !== "_") continue;
          var a = m[1].slice(0, cut), b = m[1].slice(cut + 1);
          if (known[a] && known[b]) return [a, b];
        }
        return null;
      });
      var step = span / nodes.length;
      var shown = {};
      nodes.forEach(function (n, i) {
        var when = at + i * step;
        // Opacity ONLY. Mermaid positions each node with its own transform="translate()"
        // on the same <g>, and a GSAP x/y tween rewrites that attribute — every node
        // then draws at the SVG origin, stacked on top of each other at the top of the
        // frame. This is why html.py's reveal only ever touched visibility.
        tl.fromTo(n, { opacity: 0 },
          { opacity: 1, duration: 0.3, ease: "power2.out" }, when);
        if (ids[i]) shown[ids[i]] = when;
        edges.forEach(function (e, j) {
          var pair = endpoints[j];
          // An unparseable edge has no endpoints to wait for, so it arrives with the
          // first node rather than never arriving at all.
          var ready = !pair
            ? (i === 0)
            : (shown[pair[0]] !== undefined && shown[pair[1]] !== undefined &&
               (ids[i] === pair[0] || ids[i] === pair[1]));
          if (!ready) return;
          drawEdge(e, when + 0.06);
          if (labels[j]) tl.fromTo(labels[j], { opacity: 0 }, { opacity: 1, duration: 0.24 }, when + 0.28);
        });
      });
    }

    /**
     * Draw one connector along its own length instead of fading it in.
     *
     * The arrowhead is the catch. Mermaid attaches it with `marker-end`, and a marker
     * is painted at the path's geometric end no matter how much of the stroke is
     * currently visible — so a fading-in edge shows its arrowhead parked at the
     * destination while the line is still crawling toward it. The marker is therefore
     * detached for the draw and put back with a `set` at the moment the stroke
     * arrives, which is seek-safe in a way an onComplete callback would not be.
     */
    function drawEdge(edge, at) {
      var marker = edge.getAttribute("marker-end");
      var DRAW = 0.42;
      if (marker) {
        // Stripped HERE, at build time — not with a `set` at `at`. The stroke is held
        // at 0% length from frame one, but a marker paints at the path's geometric end
        // regardless of how much stroke is visible, so scheduling the removal for the
        // moment the draw begins left every not-yet-drawn edge showing a disembodied
        // arrowhead floating in open space above its own line.
        edge.setAttribute("marker-end", "none");
        tl.set(edge, { attr: { "marker-end": marker } }, at + DRAW);
      }
      tl.fromTo(edge,
        { drawSVG: "0%" },
        { drawSVG: "100%", duration: DRAW, ease: "power1.inOut" }, at);
    }
"""


# ------------------------------------------------------------------------ the page


_STYLE = """
      :root {
        --sans: ui-sans-serif, system-ui, sans-serif;
        --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
        /* The caption band is reserved as scene padding, exactly as in html.py: the
           subtitle is an overlay and cannot push content out of its way, so the
           content is laid out above it instead. */
        --caption-bottom: 96px;
        --caption-height: 180px;
        --caption-band: calc(var(--caption-bottom) + var(--caption-height) + 56px);
      }
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1080px; height: 1920px; overflow: hidden; background: #05070d; }
      #root { position: relative; width: 100%; height: 100%; overflow: hidden;
        font-family: var(--sans); color: var(--ink); }
      /* inset:0 is not optional. The runtime stretches a root-level clip to the frame
         only when it has NO computed size; a scene sized by its own flex content keeps
         that size, and the mood plate then covers the top third of the frame with
         black underneath it. */
      .scene { position: absolute; inset: 0;
        display: flex; flex-direction: column; justify-content: center;
        padding: 150px 84px var(--caption-band); }
      /* One background for the whole reel, below every scene, so a cut never dips to
         black. It lives on a child of its clip: the framework owns clip visibility,
         and a tween on .clip is rejected outright. */
      .bg { position: absolute; inset: 0; z-index: 0; }
      .scene { z-index: 1; }
      .bgplate { position: absolute; inset: 0;
        background: var(--grid), radial-gradient(circle at 30% 20%, var(--bg-c), transparent 60%),
          linear-gradient(160deg, var(--bg-a), var(--bg-b), var(--bg-a));
        background-size: 60px 60px, 60px 60px, 220% 220%, 220% 220%; }
      .wipe { position: absolute; inset: 0; z-index: 4; overflow: hidden; }
      .wipe-bar { position: absolute; inset: -10% -20%; transform: skewX(-12deg);
        background: linear-gradient(90deg, var(--accent), var(--accent-2)); }
      .cite { position: absolute; top: 96px; left: 84px;
        font: 600 26px/1 var(--mono); letter-spacing: .04em; color: var(--muted);
        background: var(--panel); border: 1px solid var(--line);
        padding: 14px 22px; border-radius: 999px; }
      .block { position: relative; width: 100%; }
      .center { text-align: center; }
      .title { font-size: var(--title-size); font-weight: var(--head-weight);
        font-family: var(--head-font); text-transform: var(--head-case); line-height: 1.04; letter-spacing: -.02em; }
      .sub { margin-top: 32px; font-size: 44px; font-weight: 500; color: var(--muted); }
      .heading { font-size: 60px; font-weight: var(--head-weight);
        font-family: var(--head-font); text-transform: var(--head-case); line-height: 1.1;
        margin-bottom: 56px; letter-spacing: -.01em; }
      .bullets { list-style: none; display: flex; flex-direction: column; gap: 40px; }
      .bullets li { position: relative; padding-left: 56px; font-size: 46px;
        font-weight: 500; line-height: 1.28; }
      .bullets li::before { content: ""; position: absolute; left: 0; top: 20px;
        width: 26px; height: 26px; border-radius: 8px;
        background: linear-gradient(135deg, var(--accent), var(--accent-2)); }
      .diagram { display: flex; justify-content: center; align-items: center; }
      .diagram .mermaid { width: 100%; }
      /* max-width:none overrides the inline max-width mermaid stamps on its own <svg>,
         which is the natural size of the graph and leaves a six-node flowchart about a
         third of the frame wide. The height cap stops a long chain from growing into
         the caption band. */
      /* !important because mermaid writes max-width as an INLINE style on the <svg>,
         and an inline declaration beats a stylesheet one. */
      .diagram svg { width: 100%; max-width: none !important; height: auto;
        max-height: 1020px; }
      .compare { display: flex; gap: 40px; }
      .pane { flex: 1; background: var(--panel);
        border: 1px solid var(--line); border-radius: 28px; padding: 40px; }
      .pane-label { font-size: 40px; font-weight: 700; margin-bottom: 28px; color: var(--accent); }
      .pane ul { list-style: none; display: flex; flex-direction: column; gap: 22px; }
      .pane li { font-size: 34px; line-height: 1.25; color: #e2e8f0; }
      .code { background: rgba(2,6,23,.7); border: 1px solid rgba(148,163,184,.2);
        border-radius: 24px; padding: 44px; font: 500 40px/1.5 var(--mono);
        color: #e2e8f0; white-space: pre-wrap; word-break: break-word; }
      .outro-cta { font-size: 80px; font-weight: var(--head-weight);
        font-family: var(--head-font); text-transform: var(--head-case); letter-spacing: -.02em; }
      /* A doc URL is one long unbreakable token and runs straight off the right edge
         at 34px. Wrap it anywhere and let it use two lines. */
      .outro-url { margin-top: 40px; font: 500 30px/1.35 var(--mono); color: var(--accent);
        word-break: break-all; }
      /* Type on the picture, not a caption bar — a paint-order stroke under the fill
         so the letterforms stay intact over a white diagram or a dark plate. */
      /* Above scenes (z 1) and the background (z 0); only a launch wipe covers it. */
      .caption { position: absolute; z-index: 3; left: 96px; right: 96px;
        bottom: var(--caption-bottom); height: var(--caption-height); overflow: hidden;
        display: flex; align-items: flex-end; justify-content: center;
        text-align: center; text-wrap: balance;
        font-size: 46px; line-height: 1.3; font-weight: 700; letter-spacing: -.01em;
        color: #fff; paint-order: stroke fill;
        -webkit-text-stroke: 9px rgba(2,6,23,.82);
        text-shadow: 0 3px 18px rgba(2,6,23,.95), 0 1px 3px rgba(2,6,23,.9); }
"""


def build_composition(
    sb: Any,
    voiced: list[Any],
    project_dir: Path,
    *,
    music: Path | None = None,
) -> Path:
    """Write a complete HyperFrames project for one storyboard.

    Scene ``i`` starts where scene ``i-1``'s narration ended, so the picture and the
    voice share one clock and there is no join arithmetic to get wrong.

    :returns: the project directory
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    assets = project_dir / "assets"
    (assets / "audio").mkdir(parents=True, exist_ok=True)

    has_diagram = any(scene.type == "diagram" for scene in sb.scenes)
    if has_diagram:
        if not MERMAID_JS.exists():
            raise RenderUnavailable(f"mermaid bundle not found at {MERMAID_JS}")
        shutil.copy(MERMAID_JS, assets / "mermaid.min.js")

    if not GSAP_JS.exists():
        raise RenderUnavailable(f"gsap not found at {GSAP_JS} (run: npm install)")
    shutil.copy(GSAP_JS, assets / "gsap.min.js")
    # Optional: a missing plugin degrades the motion, it does not fail the render.
    plugins = [path for path in (DRAWSVG_JS, SPLITTEXT_JS) if path.exists()]
    for path in plugins:
        shutil.copy(path, assets / path.name)
    if len(plugins) < 2:
        log.warning("gsap plugins missing (%s); falling back to plain fades", plugins)

    theme = _theme(sb)
    starts: list[float] = []
    durations: list[float] = []
    elapsed = 0.0
    for spoken in voiced:
        starts.append(elapsed)
        dur = max(0.8, spoken.duration_ms / 1000)
        durations.append(dur)
        elapsed += dur
    total = elapsed

    sections: list[str] = []
    captions: list[str] = []
    audio: list[str] = []
    timeline: list[str] = []

    for index, (scene, spoken) in enumerate(zip(sb.scenes, voiced)):
        start, dur = starts[index], durations[index]
        sections.append(_scene_section(scene, index, start, dur))
        # The narration text for the no-cues fallback lives on the scene, not on Voiced.
        captions.append(_caption_clips(spoken.cues, scene.narration, index, start, dur))
        wav = assets / "audio" / f"scene{index}.wav"
        shutil.copy(spoken.wav_path, wav)
        audio.append(
            f'<audio id="vo{index}" data-start="{start:.3f}" data-duration="{dur:.3f}" '
            f'data-track-index="{30 + index}" data-volume="1" '
            f'src="assets/audio/scene{index}.wav"></audio>'
        )
        timeline.append(
            _scene_timeline(scene, index, start, dur, last=index == len(sb.scenes) - 1)
        )
    timeline.insert(0, _stage_timeline(starts, theme))

    if music and music.is_file():
        shutil.copy(music, assets / "audio" / music.name)
        audio.append(
            f'<audio id="bed" data-start="0" data-duration="{total:.3f}" '
            f'data-track-index="29" data-volume="{BED_VOLUME}" '
            f'src="assets/audio/{music.name}"></audio>'
        )

    mermaid_tag = '<script src="assets/mermaid.min.js"></script>' if has_diagram else ""
    plugin_tags = "\n    ".join(
        f'<script src="assets/{path.name}"></script>' for path in plugins
    )
    # The timeline is built inside mermaid's promise, because the diagram's nodes do
    # not exist until it resolves — and registration has to happen after the build,
    # not before it.
    body = f"""
    <script>
      if (typeof DrawSVGPlugin !== "undefined") gsap.registerPlugin(DrawSVGPlugin);
      var tl = gsap.timeline({{ paused: true }});
      var MOTION = {json.dumps({k: theme[k] for k in ("enter", "leave", "words", "ease", "stagger")})};
      var LEAVE_S = {LEAVE_S};
{_DIAGRAM_JS}
      function build() {{
      {chr(10).join(timeline)}
        window.__timelines["main"] = tl;
        tl.seek(0);
      }}
      var diagrams = document.querySelectorAll(".mermaid");
      if (!diagrams.length || typeof mermaid === "undefined") {{
        build();
      }} else {{
        mermaid.initialize({{ startOnLoad: false, theme: "base",
          themeVariables: {json.dumps({"fontFamily": "system-ui, sans-serif", "fontSize": "30px", **theme["mermaid"]})} }});
        // mermaid.run() names each diagram mermaid-<Date.now()>, and the renderer
        // freezes Date.now for determinism: every diagram got the SAME id and each
        // later one drew into the first one's SVG. Explicit ids, one at a time.
        var queue = Promise.resolve();
        Array.prototype.forEach.call(diagrams, function (pre, i) {{
          queue = queue.then(function () {{
            return mermaid.render("rw-diagram-" + i, pre.textContent)
              .then(function (out) {{ pre.innerHTML = out.svg; }});
          }});
        }});
        queue.then(build).catch(build);
      }}
    </script>"""

    css_vars = _esc(";".join(f"{k}:{v}" for k, v in theme["css"].items()))
    page = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <title>{_esc(sb.meta.title)}</title>
    <script src="assets/gsap.min.js"></script>
    {plugin_tags}
    {mermaid_tag}
    <style>{_STYLE}</style>
  </head>
  <body>
    <div id="root" style="{css_vars}" data-composition-id="main" data-start="0"
         data-duration="{total:.3f}" data-width="{settings.render_width}"
         data-height="{settings.render_height}">
      <div class="clip bg" id="bg" data-start="0" data-duration="{total:.3f}" data-track-index="27"><div class="bgplate" id="bgplate"></div></div>
      {chr(10).join(sections)}
      {_wipes(starts, theme)}
      {chr(10).join(captions)}
      {chr(10).join(audio)}
    </div>{body}
  </body>
</html>
"""
    (project_dir / "index.html").write_text(page, encoding="utf-8")
    (project_dir / "meta.json").write_text(
        '{"id": "razorwire-reel", "name": "razorwire-reel"}\n', encoding="utf-8"
    )
    log.info("wrote composition %s (%d scenes, %.2fs)", project_dir, len(sb.scenes), total)
    return project_dir


def publish_interactive(sb: Any, voiced: list[Any], media_id: str) -> str | None:
    """Publish the composition itself beside the MP4, for the feed's interactive player.

    The same page the MP4 is rendered from — same theme, motion and diagram — so the
    scrubbable reel and the video can never drift apart. Best-effort: ``None`` means the
    feed falls back to the MP4 or the DOM reel, exactly as before.

    ponytail: local media only. On Supabase storage this returns None; upload the
    directory when interactive reels are needed on the shared deployment.
    """
    if settings.supabase_storage_enabled or not RUNTIME_JS.is_file():
        return None
    try:
        name = f"{media_id}_hf"
        project = build_composition(sb, voiced, Path(settings.media_dir) / name)
        shutil.copy(RUNTIME_JS, project / "assets" / RUNTIME_JS.name)
        page = (project / "index.html").read_text(encoding="utf-8")
        tag = f'<script src="assets/{RUNTIME_JS.name}"></script>'
        (project / "play.html").write_text(page.replace("</head>", f"  {tag}\n  </head>", 1),
                                           encoding="utf-8")
        return f"/media/{name}/play.html"
    except Exception as exc:
        log.warning("could not publish the interactive composition for %s: %s", media_id, exc)
        return None


def _cli(args: list[str], cwd: Path) -> None:
    """Run the CLI; a nonzero exit raises with the tail of its output."""
    if shutil.which("npx") is None:
        raise RenderUnavailable("npx is not on PATH (install Node.js 22+)")
    result = subprocess.run(
        ["npx", "-y", CLI, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
    )
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-20:])
        raise RuntimeError(f"hyperframes {args[0]} failed:\n{tail}")


def check(project_dir: Path) -> None:
    """Lint, runtime, layout, motion and WCAG contrast, in one browser pass.

    The ffmpeg path has no equivalent: a caption sitting on top of a diagram, or a
    heading that overflowed the frame, only ever showed up by watching the MP4.

    :raises RuntimeError: if the composition has findings that gate
    """
    _cli(["check"], project_dir)


def render(project_dir: Path, out_mp4: Path, *, quality: str = "looks") -> Path:
    """Render the project to ``out_mp4``. Local only — never ``cloud render``."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    _cli(["render", "--quality", quality, "--output", str(out_mp4.resolve())], project_dir)
    if not out_mp4.is_file() or out_mp4.stat().st_size == 0:
        raise RuntimeError(f"hyperframes reported success but {out_mp4} is missing or empty")
    return out_mp4


def render_from_voiced(sb: Any, voiced: list[Any], work_dir: Path) -> Any:
    """Drop-in replacement for ``render.pipeline.render_from_voiced``."""
    from .pipeline import RenderResult

    project = build_composition(
        sb, voiced, work_dir / "composition", music=_bed()
    )
    check(project)
    mp4 = render(project, work_dir / "video.mp4")
    durations = [spoken.duration_ms for spoken in voiced]
    return RenderResult(mp4_path=mp4, duration_ms=sum(durations), scene_durations=durations)


def _bed() -> Path | None:
    """The optional music bed. Absent by default — a reel is narration first."""
    raw = settings.render_music_bed
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None
