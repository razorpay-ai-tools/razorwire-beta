"""One internal storyboard scene -> a self-contained 9:16 HTML frame.

Each scene type gets its own layout, mirroring the six feed scene components but
rendered by the backend so the MP4 pipeline has no dependency on a running web app.
Diagrams are drawn by the real Mermaid library (loaded from ``node_modules``), so
the architecture in the video is exact — the same reason the feed is trustworthy.

The page signals ``window.__ready = true`` once it has settled (immediately for
static scenes, after ``mermaid.run()`` for diagrams) so the capture step knows when
to screenshot. Captions and voice are added later by ffmpeg; they are not in here.
"""

from __future__ import annotations

import html as _html
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
MERMAID_JS = _REPO_ROOT / "node_modules" / "mermaid" / "dist" / "mermaid.min.js"

#: broll.mood -> a two-stop background gradient. Decoration only; it carries no
#: information, exactly like the Veo plate it stands in for on the free path.
_MOODS: dict[str, tuple[str, str]] = {
    "dataflow": ("#0b1220", "#123a5e"),
    "servers": ("#0b1220", "#14313a"),
    "team": ("#160f22", "#3a1f5e"),
    "money": ("#0e1a12", "#14432b"),
    "abstract": ("#0b1020", "#2a2350"),
    "city": ("#0a0f1a", "#26304a"),
}
_DEFAULT_MOOD = ("#0b1020", "#221a3f")


def _esc(value: Any) -> str:
    return _html.escape("" if value is None else str(value))


def _mood_colors(scene: Any) -> tuple[str, str]:
    broll = getattr(scene, "broll", None)
    mood = getattr(getattr(broll, "mood", None), "value", None)
    return _MOODS.get(mood, _DEFAULT_MOOD)


def _cite_chip(scene: Any) -> str:
    cite = getattr(scene, "cite", None)
    if not cite:
        return ""
    return f'<div class="cite">{_esc(cite)}</div>'


def _caption(scene: Any) -> str:
    """The spoken narration, shown as a caption bar. Burned into the frame here
    because this ffmpeg build has no subtitles filter, and it keeps captions in sync
    with the voice for free — the whole scene holds for the length of this narration."""
    narration = getattr(scene, "narration", None)
    if not narration:
        return ""
    return f'<div class="caption">{_esc(narration)}</div>'


def _content(scene: Any) -> str:
    kind = scene.type
    if kind == "title":
        sub = getattr(scene, "sub", None)
        return (
            '<div class="block center">'
            f'<h1 class="title">{_esc(scene.heading)}</h1>'
            + (f'<p class="sub">{_esc(sub)}</p>' if sub else "")
            + "</div>"
        )
    if kind == "bullets":
        items = "".join(f"<li>{_esc(item)}</li>" for item in scene.bullets)
        return (
            '<div class="block">'
            f'<h2 class="heading">{_esc(scene.heading)}</h2>'
            f'<ul class="bullets">{items}</ul>'
            "</div>"
        )
    if kind == "diagram":
        return (
            '<div class="block">'
            f'<h2 class="heading">{_esc(scene.heading)}</h2>'
            f'<div class="diagram"><pre class="mermaid">{_esc(scene.mermaid)}</pre></div>'
            "</div>"
        )
    if kind == "compare":
        return (
            '<div class="block">'
            f'<h2 class="heading">{_esc(scene.heading)}</h2>'
            '<div class="compare">'
            f"{_pane(scene.left)}{_pane(scene.right)}"
            "</div>"
            "</div>"
        )
    if kind == "code":
        heading = getattr(scene, "heading", None)
        return (
            '<div class="block">'
            + (f'<h2 class="heading">{_esc(heading)}</h2>' if heading else "")
            + f'<pre class="code"><code>{_esc(scene.code)}</code></pre>'
            + "</div>"
        )
    if kind == "outro":
        url = getattr(scene, "url", None)
        return (
            '<div class="block center">'
            f'<div class="outro-cta">{_esc(scene.cta)}</div>'
            + (f'<div class="outro-url">{_esc(url)}</div>' if url else "")
            + "</div>"
        )
    # Unreachable given the discriminated union, but never emit a blank frame.
    return f'<div class="block center"><p class="sub">{_esc(kind)}</p></div>'


def _pane(pane: Any) -> str:
    items = "".join(f"<li>{_esc(item)}</li>" for item in pane.items)
    return (
        '<div class="pane">'
        f'<div class="pane-label">{_esc(pane.label)}</div>'
        f"<ul>{items}</ul>"
        "</div>"
    )


#: Every scene defines ``window.__stepCount`` and ``window.__reveal(i)`` so the capture
#: step can screenshot a build-up instead of one still: bullets appear one by one,
#: diagrams grow node by node (an edge appears once both its endpoints have). ``reveal``
#: uses visibility, not display, so layout never shifts between steps.
_REVEAL_JS = """
  window.__stepCount = 1;
  window.__reveal = function (step) {};
  function initReveal() {
    const bullets = Array.from(document.querySelectorAll('.bullets li'));
    if (bullets.length > 1) {
      window.__stepCount = bullets.length;
      window.__reveal = function (step) {
        bullets.forEach((li, i) => { li.style.visibility = i < step ? 'visible' : 'hidden'; });
      };
      return;
    }
    const svg = document.querySelector('.diagram svg');
    if (!svg) return;
    const nodes = Array.from(svg.querySelectorAll('.node'));
    if (nodes.length < 2) return;
    const ids = nodes.map(n => (n.id.match(/flowchart-(.+)-\\d+$/) || [])[1]);
    if (ids.some(id => !id)) return;  // unparseable ids: no reveal, one still
    const idset = new Set(ids);
    const edges = Array.from(svg.querySelectorAll('.flowchart-link'));
    const labels = Array.from(svg.querySelectorAll('.edgeLabel'));
    // mermaid v11 encodes endpoints in the edge id: <prefix>-L_A_B_0. Node names may
    // contain underscores, so try every split until both halves are known nodes.
    const endpoints = edges.map(e => {
      const m = e.id.match(/-L_(.+)_\\d+$/);
      if (!m) return null;
      for (let cut = 1; cut < m[1].length - 1; cut++) {
        if (m[1][cut] !== '_') continue;
        const a = m[1].slice(0, cut), b = m[1].slice(cut + 1);
        if (idset.has(a) && idset.has(b)) return [a, b];
      }
      return null;
    });
    window.__stepCount = nodes.length;
    window.__reveal = function (step) {
      const shown = new Set(ids.slice(0, step));
      nodes.forEach((n, i) => { n.style.visibility = i < step ? 'visible' : 'hidden'; });
      edges.forEach((e, i) => {
        // An unparseable edge stays visible rather than never appearing.
        const on = !endpoints[i] || (shown.has(endpoints[i][0]) && shown.has(endpoints[i][1]));
        e.style.visibility = on ? 'visible' : 'hidden';
        if (labels[i]) labels[i].style.visibility = on ? 'visible' : 'hidden';
      });
    };
  }
"""

_MERMAID_INIT = f"""
<script>
  window.__ready = false;
  {_REVEAL_JS}
  function ready() {{ initReveal(); window.__ready = true; }}
  const nodes = document.querySelectorAll('.mermaid');
  if (nodes.length === 0 || typeof mermaid === 'undefined') {{
    ready();
  }} else {{
    try {{
      mermaid.initialize({{ startOnLoad: false, theme: 'dark',
        themeVariables: {{ fontFamily: 'Inter, system-ui, sans-serif', fontSize: '30px' }} }});
      mermaid.run({{ nodes }}).then(ready).catch(ready);
    }} catch (e) {{ ready(); }}
  }}
</script>
"""

_STATIC_READY = f"<script>{_REVEAL_JS}\ninitReveal(); window.__ready = true;</script>"


def scene_html(scene: Any, *, width: int, height: int, over_footage: bool = False) -> str:
    """Full HTML document for one scene, sized ``width`` x ``height``.

    ``over_footage`` swaps the opaque mood gradient for a translucent scrim, so the
    captured PNG keeps alpha and ffmpeg can composite it over a looping b-roll clip.
    """
    top, bottom = _mood_colors(scene)
    background = (
        "linear-gradient(180deg, rgba(2,6,23,.38), rgba(2,6,23,.66))"
        if over_footage
        else f"linear-gradient(160deg, {top}, {bottom})"
    )
    is_diagram = scene.type == "diagram"
    mermaid_tag = (
        f'<script src="file://{MERMAID_JS}"></script>' if is_diagram and MERMAID_JS.exists() else ""
    )
    ready = _MERMAID_INIT if (is_diagram and MERMAID_JS.exists()) else _STATIC_READY

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: {width}px; height: {height}px; overflow: hidden; }}
  body {{
    font-family: Inter, -apple-system, "Segoe UI", system-ui, sans-serif;
    color: #f8fafc; background: {background};
    display: flex; flex-direction: column; justify-content: center;
    padding: 150px 84px 240px;
  }}
  .cite {{
    position: absolute; top: 96px; left: 84px;
    font: 600 26px/1 "SF Mono", ui-monospace, monospace; letter-spacing: .04em;
    color: #cbd5e1; background: rgba(15,23,42,.66); border: 1px solid rgba(148,163,184,.35);
    padding: 14px 22px; border-radius: 999px;
  }}
  .block {{ width: 100%; }}
  .center {{ text-align: center; }}
  .title {{ font-size: 96px; font-weight: 800; line-height: 1.04; letter-spacing: -.02em; }}
  .sub {{ margin-top: 32px; font-size: 44px; font-weight: 500; color: #cbd5e1; }}
  .heading {{ font-size: 60px; font-weight: 700; line-height: 1.1; margin-bottom: 56px; letter-spacing: -.01em; }}
  .bullets {{ list-style: none; display: flex; flex-direction: column; gap: 40px; }}
  .bullets li {{ position: relative; padding-left: 56px; font-size: 46px; font-weight: 500; line-height: 1.28; }}
  .bullets li::before {{
    content: ""; position: absolute; left: 0; top: 20px; width: 26px; height: 26px;
    border-radius: 8px; background: linear-gradient(135deg, #60a5fa, #a78bfa);
  }}
  .diagram {{ display: flex; justify-content: center; align-items: center; }}
  .diagram .mermaid {{ width: 100%; }}
  .diagram svg {{ width: 100%; height: auto; max-height: 1100px; }}
  .compare {{ display: flex; gap: 40px; }}
  .pane {{ flex: 1; background: rgba(15,23,42,.5); border: 1px solid rgba(148,163,184,.25);
    border-radius: 28px; padding: 40px; }}
  .pane-label {{ font-size: 40px; font-weight: 700; margin-bottom: 28px;
    background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text;
    background-clip: text; color: transparent; }}
  .pane ul {{ list-style: none; display: flex; flex-direction: column; gap: 22px; }}
  .pane li {{ font-size: 34px; line-height: 1.25; color: #e2e8f0; }}
  .code {{ background: rgba(2,6,23,.7); border: 1px solid rgba(148,163,184,.2);
    border-radius: 24px; padding: 44px; font: 500 40px/1.5 "SF Mono", ui-monospace, monospace;
    color: #e2e8f0; white-space: pre-wrap; word-break: break-word; }}
  .outro-cta {{ font-size: 80px; font-weight: 800; letter-spacing: -.02em; }}
  .outro-url {{ margin-top: 40px; font: 500 34px/1 "SF Mono", ui-monospace, monospace; color: #93c5fd; }}
  .caption {{
    position: absolute; left: 72px; right: 72px; bottom: 96px; text-align: center;
    font-size: 40px; line-height: 1.34; font-weight: 500; color: #f1f5f9;
    background: rgba(2,6,23,.58); border: 1px solid rgba(148,163,184,.28);
    border-radius: 22px; padding: 26px 34px; backdrop-filter: blur(2px);
  }}
</style>
{mermaid_tag}
</head><body>
{_cite_chip(scene)}
{_content(scene)}
{_caption(scene)}
{ready}
</body></html>
"""
