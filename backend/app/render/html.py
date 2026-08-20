"""One internal storyboard scene -> a self-contained 9:16 HTML frame.

Each scene type gets its own layout, mirroring the six feed scene components but
rendered by the backend so the MP4 pipeline has no dependency on a running web app.
Diagrams are drawn by the real Mermaid library (loaded from ``node_modules``), so
the architecture in the video is exact — the same reason the feed is trustworthy.

Diagram scenes are ANIMATED: the page exposes ``window.__seek(t)`` that sets the
exact visual state at time ``t`` — boxes fade in and labelled arrows draw
themselves in flow order — so the capture step can frame-step the diagram building
itself, synced to the narration. Other scene types are static frames. Every page
signals ``window.__ready = true`` once it has settled.
"""

from __future__ import annotations

import html as _html
import json
import re
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

_DIRECTION_RE = re.compile(r"^\s*(?:graph|flowchart)\s+(TD|TB|BT|LR|RL)", re.IGNORECASE)


def _esc(value: Any) -> str:
    return _html.escape("" if value is None else str(value))


def _mood_colors(scene: Any) -> tuple[str, str]:
    broll = getattr(scene, "broll", None)
    mood = getattr(getattr(broll, "mood", None), "value", None)
    return _MOODS.get(mood, _DEFAULT_MOOD)


def _direction(mermaid: str) -> str:
    match = _DIRECTION_RE.match(mermaid or "")
    return match.group(1).upper() if match else "TD"


def is_animated(scene: Any) -> bool:
    """A diagram scene is drawn frame-by-frame; every other type is a static frame."""
    return getattr(scene, "type", None) == "diagram" and MERMAID_JS.exists()


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


# Animated diagram: __seek(t) reveals boxes (opacity) and draws arrows (stroke
# dashoffset) in flow order. Re-queries the live DOM every call because Mermaid v11
# swaps the SVG after run() resolves; ordering is by on-screen position, and boxes
# animate opacity only so we never override Mermaid's positioning transform.
_ANIM_SCRIPT = r"""
<script>
window.__ready=false;
const DURATION_MS=__DUR__, DIR="__DIR__", FADE=600, DRAW=850;
const clamp=x=>Math.max(0,Math.min(1,x));
function collect(){
  const svg=document.querySelector('.mermaid svg'); if(!svg) return [];
  const along=el=>{try{const r=el.getBoundingClientRect();return (DIR==='LR'||DIR==='RL')?r.left+r.width/2:r.top+r.height/2;}catch(e){return 1e9;}};
  const nodes=[...svg.querySelectorAll('g.node')];
  let edges=[...svg.querySelectorAll('g.edgePaths path')];
  if(!edges.length) edges=[...svg.querySelectorAll('path.flowchart-link')];
  const labels=[...svg.querySelectorAll('g.edgeLabels .edgeLabel')];
  const items=[];
  nodes.forEach(el=>items.push({el,type:'node',p:along(el)}));
  edges.forEach(el=>items.push({el,type:'edge',p:along(el),len:(el.getTotalLength?el.getTotalLength():0)}));
  labels.forEach(el=>items.push({el,type:'label',p:along(el)}));
  items.sort((a,b)=>a.p-b.p);
  return items;
}
window.__seek=function(t){
  const items=collect();
  const STEP=(DURATION_MS*0.88)/Math.max(items.length,1);
  items.forEach((it,i)=>{
    const local=t-i*STEP;
    if(it.type==='edge'){
      it.el.style.opacity=local>=0?1:0;
      if(it.len){it.el.style.strokeDasharray=it.len;it.el.style.strokeDashoffset=it.len*(1-clamp(local/DRAW));}
    }else{
      it.el.style.opacity=clamp(local/FADE);
    }
  });
};
mermaid.initialize({startOnLoad:false,theme:'dark',
  themeVariables:{fontFamily:'Inter, system-ui, sans-serif',fontSize:'30px',lineColor:'#93c5fd'}});
mermaid.run({querySelector:'.mermaid'}).then(()=>{window.__seek(0);window.__ready=true;})
  .catch(()=>{window.__ready=true;});
</script>
"""

_STATIC_READY = "<script>window.__ready = true;</script>"


# Synced diagram walkthrough: each hop is revealed when its narration beat starts
# (T = per-beat start times in ms), and the caption shows the beat being spoken. The
# reveal is grouped by hop (a new group begins at each edge), so a box + its incoming
# arrow appear together exactly as that step is narrated. Guaranteed in sync because
# both the diagram and the timeline come from the same steps.
_SYNC_SCRIPT = r"""
<script>
window.__ready=false;
const T=__T__, BEATS=__BEATS__, FADE=600, DRAW=850;
const clamp=x=>Math.max(0,Math.min(1,x));
function collect(){
  const svg=document.querySelector('.mermaid svg'); if(!svg) return [];
  const along=el=>{try{const r=el.getBoundingClientRect();return r.top+r.height/2;}catch(e){return 1e9;}};
  const nodes=[...svg.querySelectorAll('g.node')];
  let edges=[...svg.querySelectorAll('g.edgePaths path')];
  if(!edges.length) edges=[...svg.querySelectorAll('path.flowchart-link')];
  const labels=[...svg.querySelectorAll('g.edgeLabels .edgeLabel')];
  const items=[];
  nodes.forEach(el=>items.push({el,type:'node',p:along(el)}));
  edges.forEach(el=>items.push({el,type:'edge',p:along(el),len:(el.getTotalLength?el.getTotalLength():0)}));
  labels.forEach(el=>items.push({el,type:'label',p:along(el)}));
  items.sort((a,b)=>a.p-b.p);
  return items;
}
window.__seek=function(t){
  let bi=0; for(let i=0;i<T.length;i++){ if(t>=T[i]) bi=i; }
  const cap=document.querySelector('.caption'); if(cap) cap.textContent=BEATS[bi]||'';
  const items=collect();
  let group=0, lastType='node';
  items.forEach(it=>{
    if((it.type==='edge'||it.type==='label') && lastType==='node') group++;
    const revealAt = group===0 ? 0 : (T[group-1] ?? 0);
    const local=t-revealAt;
    if(it.type==='edge'){
      it.el.style.opacity=local>=0?1:0;
      if(it.len){it.el.style.strokeDasharray=it.len;it.el.style.strokeDashoffset=it.len*(1-clamp(local/DRAW));}
    }else{ it.el.style.opacity=clamp(local/FADE); }
    lastType=it.type;
  });
};
mermaid.initialize({startOnLoad:false,theme:'dark',
  themeVariables:{fontFamily:'Inter, system-ui, sans-serif',fontSize:'30px',lineColor:'#93c5fd'}});
mermaid.run({querySelector:'.mermaid'}).then(()=>{window.__seek(0);window.__ready=true;})
  .catch(()=>{window.__ready=true;});
</script>
"""


def scene_html(
    scene: Any,
    *,
    width: int,
    height: int,
    duration_ms: int = 0,
    beats: list[str] | None = None,
    beat_starts: list[int] | None = None,
) -> str:
    """Full HTML document for one scene, sized ``width`` x ``height``.

    For a diagram scene, ``beats`` + ``beat_starts`` produce a SYNCED walkthrough:
    each hop is revealed and captioned exactly when its narration beat starts. Without
    them a diagram still animates, evenly paced over ``duration_ms``. Other scenes are
    static frames. Diagram scenes expose ``window.__seek(t)`` for the capture step.
    """
    top, bottom = _mood_colors(scene)
    animate = is_animated(scene)
    synced = bool(animate and beats and beat_starts)
    mermaid_tag = f'<script src="file://{MERMAID_JS}"></script>' if animate else ""
    if synced:
        ready = _SYNC_SCRIPT.replace("__T__", json.dumps(list(beat_starts))).replace(
            "__BEATS__", json.dumps(list(beats))
        )
        caption_html = '<div class="caption"></div>'  # filled per-beat by __seek
    elif animate:
        ready = _ANIM_SCRIPT.replace("__DUR__", str(duration_ms or 8000)).replace(
            "__DIR__", _direction(scene.mermaid)
        )
        caption_html = _caption(scene)
    else:
        ready = _STATIC_READY
        caption_html = _caption(scene)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: {width}px; height: {height}px; overflow: hidden; }}
  body {{
    font-family: Inter, -apple-system, "Segoe UI", system-ui, sans-serif;
    color: #f8fafc; background: linear-gradient(160deg, {top}, {bottom});
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
{caption_html}
{ready}
</body></html>
"""
