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


_CUE_PUNCT = ".,;:!?—"


def caption_cues(text: str, start_ms: int, dur_ms: int, max_words: int = 7) -> list[tuple[int, str]]:
    """Break ``text`` into short subtitle cues (a few words each, split at natural
    punctuation) and time each to when it is spoken — a cue's start is proportional to
    how far into the text it begins, across ``dur_ms`` from ``start_ms``. So a scene's
    narration rolls as short film-style subtitles instead of one wall of text."""
    text = (text or "").strip()
    if not text:
        return []
    cues: list[str] = []
    cur: list[str] = []
    for word in text.split():
        cur.append(word)
        clause_end = word[-1:] in _CUE_PUNCT
        if len(cur) >= max_words or (clause_end and len(cur) >= 3):
            cues.append(" ".join(cur))
            cur = []
    if cur:
        cues.append(" ".join(cur))
    total = sum(len(c.split()) for c in cues) or 1
    out: list[tuple[int, str]] = []
    acc = 0
    for cue in cues:
        out.append((start_ms + int(acc / total * dur_ms), cue))
        acc += len(cue.split())
    return out


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
const DURATION_MS=__DUR__, DIR="__DIR__", CUES=__CUES__, FADE=600, DRAW=850;
const clamp=x=>Math.max(0,Math.min(1,x));
function setCap(t){if(!CUES.length)return;let i=-1;for(let k=0;k<CUES.length;k++){if(t>=CUES[k][0])i=k;}const c=document.querySelector('.caption');if(c)c.textContent=i>=0?CUES[i][1]:'';}
function collect(){
  const svg=document.querySelector('.mermaid svg'); if(!svg) return [];
  const along=el=>{try{const r=el.getBoundingClientRect();return (DIR==='LR'||DIR==='RL')?r.left+r.width/2:r.top+r.height/2;}catch(e){return 1e9;}};
  const nodes=[...svg.querySelectorAll('g.node')];
  let edges=[...svg.querySelectorAll('g.edgePaths path')];
  if(!edges.length) edges=[...svg.querySelectorAll('path.flowchart-link')];
  const labels=[...svg.querySelectorAll('g.edgeLabels g.edgeLabel')];
  const items=[];
  nodes.forEach(el=>items.push({el,type:'node',p:along(el)}));
  edges.forEach(el=>items.push({el,type:'edge',p:along(el),len:(el.getTotalLength?el.getTotalLength():0)}));
  labels.forEach(el=>items.push({el,type:'label',p:along(el)}));
  items.sort((a,b)=>a.p-b.p);
  return items;
}
window.__seek=function(t){
  setCap(t);
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


# Non-diagram scenes don't animate, but the caption still rolls its cues over time, so
# they are frame-stepped too — __seek just advances the subtitle to the phrase being spoken.
_CAPTION_SCRIPT = r"""
<script>
window.__ready=false;
const CUES=__CUES__;
function setCap(t){if(!CUES.length)return;let i=-1;for(let k=0;k<CUES.length;k++){if(t>=CUES[k][0])i=k;}const c=document.querySelector('.caption');if(c)c.textContent=i>=0?CUES[i][1]:'';}
window.__seek=function(t){ setCap(t); };
window.__seek(0); window.__ready=true;
</script>
"""


# Synced diagram walkthrough: each hop is revealed when its narration beat starts
# (T = per-beat start times in ms), and the caption shows the beat being spoken. Nodes
# and edges are indexed by their sorted on-screen position (top-to-bottom for graph TD),
# and mapped to a hop by that index: node 0 is on screen from the start, node i appears
# when hop i-1 is narrated, and edge i (with its label) draws on hop i's beat. Indexing
# per-type is deliberate — the earlier running-counter over a single mixed list was
# thrown off by mermaid's empty edge-label elements (which cluster at the top of the SVG)
# and by the group count overshooting T, which silently revealed the last node at t=0.
# Any index past the end of T clamps to the final beat, so nothing ever snaps to the start.
_SYNC_SCRIPT = r"""
<script>
window.__ready=false;
const T=__T__, CUES=__CUES__, FADE=600, DRAW=850;
const clamp=x=>Math.max(0,Math.min(1,x));
const LAST=T.length?T[T.length-1]:0;
const along=el=>{try{const r=el.getBoundingClientRect();return r.top+r.height/2;}catch(e){return 1e9;}};
function setCap(t){if(!CUES.length)return;let i=-1;for(let k=0;k<CUES.length;k++){if(t>=CUES[k][0])i=k;}const c=document.querySelector('.caption');if(c)c.textContent=i>=0?CUES[i][1]:'';}
function collect(){
  const svg=document.querySelector('.mermaid svg'); if(!svg) return null;
  const nodes=[...svg.querySelectorAll('g.node')].sort((a,b)=>along(a)-along(b));
  let edges=[...svg.querySelectorAll('g.edgePaths path')];
  if(!edges.length) edges=[...svg.querySelectorAll('path.flowchart-link')];
  edges.sort((a,b)=>along(a)-along(b));
  // One group per edge ('g.edgeLabels g.edgeLabel'; the inner text is a <span>, not a
  // <g>), and drop mermaid's empty labels (rendered even for unlabelled edges).
  const labels=[...svg.querySelectorAll('g.edgeLabels g.edgeLabel')]
    .filter(el=>el.textContent.trim()).sort((a,b)=>along(a)-along(b));
  return {nodes, edges, labels};
}
window.__seek=function(t){
  setCap(t);
  const c=collect(); if(!c) return;
  c.nodes.forEach((el,i)=>{ const r=i===0?0:(T[i-1]??LAST); el.style.opacity=clamp((t-r)/FADE); });
  c.edges.forEach((el,i)=>{
    const r=(T[i]??LAST), local=t-r;
    el.style.opacity=local>=0?1:0;
    const len=el.getTotalLength?el.getTotalLength():0;
    if(len){el.style.strokeDasharray=len;el.style.strokeDashoffset=len*(1-clamp(local/DRAW));}
  });
  c.labels.forEach((el,i)=>{ const r=(T[i]??LAST); el.style.opacity=clamp((t-r)/FADE); });
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
    caption_cues: list[tuple[int, str]] | None = None,
) -> str:
    """Full HTML document for one scene, sized ``width`` x ``height``.

    Every scene exposes ``window.__seek(t)`` and is frame-stepped, so the caption rolls
    ``caption_cues`` (short phrases timed to the audio) like film subtitles. A diagram
    scene additionally draws itself: with ``beats`` + ``beat_starts`` each hop is revealed
    when its narration beat starts, otherwise it is evenly paced over ``duration_ms``.
    """
    top, bottom = _mood_colors(scene)
    animate = is_animated(scene)
    synced = bool(animate and beats and beat_starts)
    mermaid_tag = f'<script src="file://{MERMAID_JS}"></script>' if animate else ""
    cues_json = json.dumps([[int(at), txt] for at, txt in (caption_cues or [])])
    # With cues the caption rolls (filled per-cue by __seek); without them (a direct call
    # or the browser reel) fall back to the full narration as a static caption.
    caption_html = '<div class="caption"></div>' if caption_cues else _caption(scene)
    if synced:
        ready = _SYNC_SCRIPT.replace("__T__", json.dumps(list(beat_starts))).replace(
            "__CUES__", cues_json
        )
    elif animate:
        ready = (
            _ANIM_SCRIPT.replace("__DUR__", str(duration_ms or 8000))
            .replace("__DIR__", _direction(scene.mermaid))
            .replace("__CUES__", cues_json)
        )
    else:
        ready = _CAPTION_SCRIPT.replace("__CUES__", cues_json)

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
  /* Edge labels: a subtle dark chip with light text instead of mermaid's opaque grey
     box, so a labelled arrow reads cleanly and does not flash an empty grey box while
     the label fades in. */
  .diagram .edgeLabel .labelBkg,
  .diagram .edgeLabel foreignObject > div {{
    background-color: rgba(11,16,32,.92) !important; border-radius: 10px;
  }}
  .diagram .edgeLabel, .diagram .edgeLabel p, .diagram .edgeLabel span {{
    color: #dbe4f3 !important; font-size: 26px !important; font-weight: 500;
    background-color: transparent !important;
  }}
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
  /* A compact, film-style subtitle: one short phrase at a time, centred, hugging its
     text (short cue -> small box) instead of a full-width multi-sentence block. */
  .caption {{
    position: absolute; left: 50%; bottom: 120px; transform: translateX(-50%);
    max-width: 80%; width: max-content; text-align: center;
    font-size: 42px; line-height: 1.25; font-weight: 600; color: #f8fafc;
    background: rgba(2,6,23,.66); border: 1px solid rgba(148,163,184,.26);
    border-radius: 16px; padding: 14px 30px; text-shadow: 0 2px 8px rgba(0,0,0,.55);
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
