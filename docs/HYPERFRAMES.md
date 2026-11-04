# Rendering reels with HyperFrames

**This is the default engine.** Same storyboard, same narration, same citations as the
ffmpeg path — a different way of making the picture.

A box without Node 22+ needs no configuration: `render_from_voiced` catches the
missing toolchain and falls back to ffmpeg, so the default is safe to ship ahead of
the deploy image. Set `RENDER_ENGINE=ffmpeg` to force the old path.

```bash
cd backend
.venv/bin/python scripts/render_hyperframes_demo.py \
  ../src/lib/fixtures/otm-rearch.storyboard.json /tmp/reel.mp4
```

---

## Why

The ffmpeg path renders each scene as a **still** (or a short stack of stills) and
joins them with `xfade`. Everything that should read as motion has to be faked with
cross-faded screenshots, and three awkward things follow from that:

| Today | Why it is that way |
|---|---|
| Transitions are `fadeblack`, not a dissolve | Two consecutive scenes put their heading and caption in the same two places. A cross-dissolve shows both texts at once — `compose.py:43` says so in as many words. |
| Subtitles need a second capture pass on a transparent plate | `html.__layer` drops the page background to get alpha, so ffmpeg can hard-**cut** a caption over content that is still fading. |
| `compose._join_filter` carries offset arithmetic | `xfade` overlaps its inputs, so every segment is padded by `SCENE_XFADE_S` to stop the visuals drifting ahead of the voice, once per join, cumulatively. |

In a composition none of those are problems that get *solved* — they stop existing:

- A scene's elements animate individually, so nothing is ever a cross-fade between two
  whole frames. No blackout needed between sections.
- A subtitle is **its own timed clip**. A cut is what happens by default. The alpha
  plate and the second capture pass are gone.
- Clips are absolutely timed on one clock, so there is no join arithmetic. Scene *i*
  starts where scene *i-1*'s narration ended, and that is the whole calculation.

And one thing we simply did not have before: `hyperframes check` runs lint, a runtime
error pass, a **layout overflow** audit and a **WCAG AA contrast** audit in one browser
pass, before a single frame is encoded. The `--caption-band` contract in `html.py`
exists because captions once landed on top of diagrams; that class of bug is now caught
mechanically rather than by watching the MP4.

## What is unchanged

Deliberately, all of it:

- The storyboard contract, its validators, and the self-repair loop.
- **Scene length is the measured length of its narration wav.** Both engines take the
  same `Voiced` records; a reel is timed identically either way.
- The citation chip on every scene.
- The Mermaid diagram, drawn by the real library, built up node by node, with an edge
  appearing only once both its endpoints have. The endpoint-parsing rule is ported from
  `html._REVEAL_JS` unchanged.
- Cue splitting in `tts.py` — `_CUE_MAX_CHARS`, sentence breaks, `_merge_short`.

## What changes on screen

- Headings arrive **a word at a time** (GSAP SplitText, masked per line), bullets one
  at a time, comparison panes sliding in from their own sides, diagram nodes fading in
  along the flow. Previously: a still, cross-faded.
- Connectors **draw along their own length** (GSAP DrawSVG) rather than fading in. Both
  plugins were Club-only until GSAP 3.13 and are now free including commercial use;
  they are vendored from `node_modules`, so a render needs no network.
- No dip to black between scenes.
- Diagrams are full-frame width instead of roughly a third of it (mermaid stamps its own
  `max-width` inline; we override it).
- Optional low music bed under the narration — `RENDER_MUSIC_BED=/path/to/track.mp3`,
  off by default.

## The seam

```
storyboard + [Voiced]
        │
        ├── render_engine="ffmpeg"       html.py → capture.py → compose.py → MP4
        └── render_engine="hyperframes"  hyperframes.py → `npx hyperframes` → MP4
```

`render/pipeline.py:render_from_voiced` dispatches. Both return the same
`RenderResult`, so nothing above the render stage knows which ran.

## Operational notes

- **Wants Node 22+ on PATH**, but does not require it: a missing toolchain raises
  `RenderUnavailable`, which drops to the ffmpeg path with a warning. Only that error
  falls back — a composition that fails `check` raises `RuntimeError` and still fails
  loudly, because that is our bug and hiding it behind a lesser reel helps nobody.
  The CLI is pinned (`hyperframes@0.8.47`) so a reel re-renders identically later.
- **Local render only.** `hyperframes cloud render` would upload the composition to a
  third party, and these frames are derived from internal documents. The code calls
  `render`, never `cloud render` — keep it that way.
- Telemetry is anonymous and excludes composition content; `npx hyperframes telemetry
  disable` if that is still not wanted on a build box.
- Playwright is still needed by the ffmpeg path. If `hyperframes` becomes the only
  engine, `capture.py`, `compose.py` and the Playwright dependency all go — about 470
  lines of ffmpeg filtergraph, deleted rather than maintained.

## Measured on the sample storyboard

`src/lib/fixtures/otm-rearch.storyboard.json`, 6 scenes, Kokoro `af_heart`:

```
voiced: 67.9s total, cues per scene: [4, 6, 5, 7, 7, 2]
check:  passed
render: 5.3 MB, 1080x1920
```

And two real generations through the running service, queue to feed:

```
"UPI Mandates: Why block_fund Never Turns Off"   5 scenes  65.5s  -16.05 LUFS  frame0 luma 29.8
"Don't Trust the Model, Measure the Audio"       6 scenes  66.5s  -16.02 LUFS  frame0 luma 31.3
```

Both clean on the QA pass, both serving their MP4 and poster over HTTP.

## Known gaps

- **b-roll.** The ffmpeg path composites scene PNGs over a looping `<mood>.mp4` from
  `broll_dir`. The composition currently uses the mood gradient only. A `<video>` clip
  behind the scene plate is the fix, and it is the one feature parity gap.
- **No beat sync.** The bed, when enabled, is a flat low track. Scene starts are driven
  by narration, which is correct — but a bed whose downbeats fell near scene boundaries
  would sound composed rather than laid under.

Loudness and poster frames are no longer on this list: both engines now run the
post-render pass in `render/qa.py` and `render/poster.py`. See
[`OUTPUT-QUALITY.md`](./OUTPUT-QUALITY.md) for those and for the ranked list of what
else is worth adding.
