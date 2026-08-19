# Render Pipeline — storyboard.json → MP4 → feed

> Design doc for the **voice → render → publish** half of Razorwire: it turns a
> validated `storyboard.json` into a narrated, animated 9:16 MP4 and publishes it
> to the feed. Owned by Shivang + [pair]. The *script* half (AIDoc → storyboard)
> is owned separately; the storyboard contract is the only thing shared.

Status: **design** · Branch: `feat/video-render-pipeline` · Depends on: `backend/app/storyboard.py` (the contract), `src/components/scenes/*` (the scene templates).

---

## 1. What this half does, and where it sits

The pipeline is one job with a state machine (already modelled in `Job`):

```
queued → scripting → voicing → rendering → published | failed
         └─ other half ─┘      └──────── this doc ────────┘
```

`backend/app/pipeline.py` implements only `scripting` today. Its own docstring says
*"Stages 2 and 3 (voice, visuals) are only needed for the MP4 export path."* Those two
stages plus publish are exactly this design. The `voicing`/`rendering` job states and the
`Post.media_url` column (*"the rendered MP4 export once one exists"*) are already reserved
for us — we fill them in.

**Deliverable:** clicking *Generate* produces a real `.mp4` that plays on the page and lives
in the feed, with the doc's real architecture diagram and a citation on every factual scene.

---

## 2. End-to-end flow, from the user's click

```
┌ USER (browser) ────────────────────────────────────────────────────────────┐
│ 1. Paste an AIDoc URL (or a topic) → click Generate                          │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ POST /generate {kind, docId|input}
                ▼
┌ OUR BACKEND (FastAPI, background job) ───────────────────────────────────────┐
│ 2. scripting   fetch doc (aidocs) → Claude emit_storyboard → storyboard.json  │  ← other half
│ 3. voicing     Kokoro TTS per scene → sceneN.wav + measured durationMs        │  ◀ OURS
│ 4. rendering   Playwright frames from /render + ffmpeg → video.mp4 + poster   │  ◀ OURS
│ 5. publish     write mp4 to /media, INSERT Post row, set job.post_id          │  ◀ OURS
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ job.state = "published", job.post_id = post_xxx
                ▼
┌ USER (browser) ────────────────────────────────────────────────────────────┐
│ 6. poll GET /jobs/{id} shows the live states; on published, load the post     │
│ 7. <video src="/media/xxx.mp4"> plays the MP4 (first frame = poster)          │
└───────────────────────────────────────────────────────────────────────────────┘
```

The sibling **upload-clip** path (`POST /uploads` → `POST /posts` kind=`clip`) already exists
and is unchanged by this work; it's mentioned only so the two feed post kinds stay distinct.

---

## 3. The input contract (recap — see `storyboard.py` for the truth)

```jsonc
{ "meta":   { "title": "...", "tags": ["upi"] },
  "source": { "kind": "aidoc|slack|topic", "docId": "...", "url": "...", "title": "..." },
  "scenes": [ /* 4–6 scenes, one of six types each */ ] }
```

Six scene types, each with its own visual: **`title`**, **`bullets`**, **`compare`**,
**`diagram`** (the only one carrying Mermaid), **`code`**, **`outro`**. Every scene has
`narration` (spoken) and, for factual scenes from a grounded source, a `cite`.

Two fields are **pipeline-owned** and set by *us*, never the model:
- `scene.durationMs` — set in **voicing**, from the measured narration audio length.
- `scene.broll.clipId` — set in **rendering** by the resolver (mood → clip / gradient).

`validate_storyboard(sb, stage="render")` enforces that both are present before we render —
so a desynced or half-resolved storyboard fails loudly instead of producing a broken video.

Build/test fixture (no LLM needed): `src/lib/fixtures/otm-rearch.storyboard.json`.

---

## 4. What the video looks like (and what it is not)

Each scene becomes a **fully composed, animated 9:16 frame**, held for the length of its
narration, with voiceover and captions. It is a **motion-graphics explainer**, not a slideshow
and not live-action footage.

Per-scene visual + motion:

| Scene | Visual | Motion |
|---|---|---|
| `title` | heading + sub on an animated background | text fades/rises in; slow push-in |
| `bullets` | 2–4 short phrases | bullets stagger in one by one |
| `compare` | two labelled panes (Legacy / Rearch) | panes slide in from opposite sides |
| `diagram` | **Mermaid** architecture graph | nodes/edges draw on in flow order |
| `code` | a short snippet | lines reveal top-to-bottom |
| `outro` | CTA + link | gentle fade |

Every frame also carries: a **moving background** keyed by `broll.mood` (animated
gradient/particles — free; a real Veo clip later if the library exists), a **caption line**
synced to the voice, and the **`cite` chip** on factual scenes. Between scenes: a short
crossfade.

**Honest ceiling:** Mermaid draws *only* the `diagram` scene; the rest are their own
components. And we do not generate cinematic/AI-imagined footage — that's the Sora/Veo path we
rejected because it can't render an accurate diagram and costs per second. The output feels
like a produced 60-second explainer reel; it is animated, narrated, and accurate.

---

## 5. The three stages in detail

### 5.1 Voicing — `backend/app/render/tts.py`

- Input: the script-stage `Storyboard`.
- For each scene, synthesize `scene.narration` with **Kokoro-82M** (local, Apache-2.0, no
  egress) → `scenes/<i>.wav`.
- Measure each wav's duration → set `scene.durationMs` (round up; floor at the schema min of
  800 ms). Total = sum → the post's `duration_ms`.
- Run the **broll resolver** (`resolve_broll`, already in `pipeline.py`): `mood → clipId`. With
  no Veo library, `clipId` resolves to a gradient sentinel (e.g. `"gradient:abstract"`) so the
  render-stage contract is satisfied and `/render` knows to draw the animated gradient.
- Re-validate with `stage="render"`.
- Output: the storyboard with `durationMs` + `clipId` filled, plus the wav files.

*Why voice before render:* scene length is driven by real audio, never guessed — this is the
contract's core anti-desync rule.

### 5.2 Rendering — `backend/app/render/capture.py` + `compose.py`

**Capture (Playwright):**
- A headless Chromium (driven from Python) loads our own web app's new **`/render`** route
  (§6), which draws a single scene at a single instant, deterministically.
- For each scene we step time `t` from 0 → `durationMs` at a target **fps (default 24)** and
  screenshot each frame. Animations are a pure function of `t`, so each screenshot is
  reproducible. We reuse one page and advance `t` via `page.evaluate` (no re-navigation per
  frame — much faster).
- **Perf guard:** capture frames densely only across each scene's *motion window* (first
  ~1.2 s), then hold the last frame for the static remainder (ffmpeg extends it). A 60 s reel
  is then ~a few hundred screenshots, not ~1,800. fps and motion-window are config.

**Compose (ffmpeg):**
- Per scene: image sequence (at fps) + `<i>.wav` → a scene clip whose length equals the audio.
- Concatenate scene clips with short crossfades → `video.mp4` (H.264, 720×1280, yuv420p).
- Captions and the cite chip are already *in the DOM*, so they're in the frames — no separate
  subtitle track needed.
- Poster: the `<video>` tag uses the first frame automatically (no thumbnail column).

### 5.3 Publish — `backend/app/render/publish.py`

- Write `video.mp4` to `MEDIA_DIR` (served at `/media/<id>.mp4`; local disk now, S3 later —
  no schema change).
- `INSERT` a `Post`: `kind="generated"`, `media_url="/media/<id>.mp4"`, `duration_ms`,
  `storyboard` (the JSON — powers the citation/"Spec" view), `source_doc_id`, `title`/`tags`
  from `meta`, `author_id = job.requester_id`.
- Set `job.state="published"`, `job.post_id=<new id>`, `progress=100`.

---

## 6. The new `/render` route (frontend)

The only genuinely new UI. It reuses the existing `SceneView` dispatcher and the six scene
components; it does **not** duplicate any scene visuals.

- Route: `GET /render?post=<id>&scene=<i>&t=<ms>` (or storyboard passed via a store) — renders
  **one** scene, frozen at instant `t`, as a self-contained 9:16 frame: animated background
  (mood) + scrim + `SceneView` content + caption line for `t` + cite chip. No feed chrome
  (no progress rail, no like buttons).
- **Deterministic seek:** unlike the live feed (which animates on mount via wall-clock, see
  `useReel`), `/render` drives every animation from `t` — e.g. CSS `animation-delay: -t ms;
  animation-play-state: paused`, or a `progress = t/window` prop. Screenshot at `t` is then
  identical every run.
- Caption at `t`: reuse `captionsFor(scene)` + the proportional-by-char-count timing already in
  `useReel`, selecting the line active at `t`.

---

## 7. Storage & data model

Nothing new in the schema. Files live on disk; the DB stores pointers + metadata.

| Artifact | Where |
|---|---|
| `video.mp4` | file → `MEDIA_DIR`, served `/media/<id>.mp4` |
| `Post.media_url`, `duration_ms`, `storyboard`, `source_doc_id`, `kind`, `title`, `tags`, `author_id` | DB (`posts`) |
| `Job.state`, `progress`, `post_id`, `storyboard` | DB (`jobs`) |
| per-scene `.wav`, frame PNGs | scratch dir, deleted after compose |

Small frontend touch: the feed's `GeneratedPost` should **play `<video src=media_url>` when
present**, and fall back to the live browser reel when it isn't. The storyboard stays on the
post for the citation/"Spec" view.

---

## 8. APIs & data flow

| Step | Caller → callee | Request | Response | External? | Cost |
|---|---|---|---|---|---|
| Generate | browser → our API | `POST /generate {kind,docId}` | `202 {id,state:"queued"}` | no | free |
| Poll | browser → our API | `GET /jobs/{id}` (~1/s) | `{state,progress,postId}` | no | free |
| Fetch doc | backend → aidocs | pull `docId` | doc text/sections | Razorpay-internal | free |
| Storyboard | backend → Claude | `POST /v1/messages` + `emit_storyboard` tool | tool_use → storyboard | **internet** | **paid ¢** |
| Voice | backend → Kokoro (in-proc) | `tts(narration)` | wav + duration | no | free |
| Frames | backend → local Chromium → our `/render` | `GET /render?...` + screenshot | PNGs | no | free |
| Stitch | backend → ffmpeg (subprocess) | `ffmpeg …` | mp4 + poster | no | free |
| Publish | backend → our DB | INSERT Post / UPDATE Job | rows committed | no | free |
| Play | browser → our API | `GET /feed`, `GET /media/x.mp4` | posts; mp4 bytes | no | free |

Only Claude leaves our perimeter for money, and that's the other half.

---

## 9. Module layout

```
backend/app/render/
  __init__.py
  tts.py       storyboard → per-scene wav + durationMs        (Kokoro)
  broll.py     mood → clipId / gradient sentinel               (resolver; wraps resolve_broll)
  capture.py   storyboard → per-scene frame PNGs               (Playwright → /render)
  compose.py   frames + wav → video.mp4 + poster frame         (ffmpeg)
  publish.py   mp4 → MEDIA_DIR + Post row + job.post_id
  pipeline.py  orchestrates voicing→rendering→publish; called by main._run_job
```

Each module takes a storyboard (+ a scratch dir) and returns the next artifact, so each is
unit-testable against the fixture with **no LLM and no network**.

Wiring: `main._run_job` currently stops after `scripting`. Extend it to advance
`voicing → rendering → published`, updating `job.progress` at each stage.

---

## 10. Error handling & fallbacks

| Failure | Handling |
|---|---|
| Mermaid invalid / >7 nodes | already rejected at script stage; if it slips through, `/render` shows the diagram or the scene downgrades to bullets — never a broken frame |
| Kokoro synthesis fails for a scene | retry once; then a bundled fallback voice; then fail the job with a readable error |
| A frame screenshot times out | retry that frame; then fail the job with the scene index |
| ffmpeg non-zero exit | fail the job, surface stderr tail in `job.error` |
| Web app (`/render`) not reachable | fail fast with a clear "start the web app" error; `RENDER_BASE_URL` is configurable |
| Demo-day latency | **pre-render the demo doc's MP4** and keep it in `public/`; the live browser reel is the zero-wait fallback |

---

## 11. Tooling, licenses, install, config

| Tool | Role | License | Install |
|---|---|---|---|
| Kokoro-82M | TTS | Apache-2.0 | `pip install kokoro` (+ `espeak-ng` system pkg for phonemes) |
| Playwright | headless capture | Apache-2.0 | `pip install playwright && playwright install chromium` |
| ffmpeg | mux | LGPL | `brew install ffmpeg` |
| Mermaid | diagrams | MIT | already a web dep |

New settings (in `config.py`): `RENDER_BASE_URL` (default `http://localhost:3000`),
`RENDER_FPS` (24), `RENDER_MOTION_WINDOW_MS` (1200), `KOKORO_VOICE`, `MEDIA_DIR` (exists).
All free, all local; the renderer needs the web app running (true in `dev:all`).

---

## 12. Build order (fixture-first) & risks

1. **`/render` route** renders the fixture's scenes, frozen, deterministically. *Checkpoint: open `/render?...` and see each scene.*
2. **capture + compose** on the fixture → an MP4 with silent frames. *Checkpoint: a real .mp4 plays, no LLM.*
3. **tts** → real narration + durations wired in. *Checkpoint: narrated MP4 from the fixture.*
4. **publish** → Post row + feed plays the MP4. *Checkpoint: Generate-less publish of the fixture shows in the feed.*
5. **wire into `_run_job`** so `POST /generate` runs the whole chain. *Checkpoint: end-to-end from a topic/AIDoc.*
6. Motion polish (diagram build-on, staggered bullets, backgrounds, crossfades) + pre-render demo backup.

Risks: Kokoro's `espeak-ng` dependency (mitigate: verify install Day 0, fallback voice ready);
frame-capture wall-clock (mitigate: fps + motion-window + reuse page + pre-render demo);
deterministic animation seek in `/render` (the one genuinely new frontend technique).

## 13. Out of scope

Real Veo b-roll library, S3, HLS/transcoding, per-word caption alignment, thumbnails table,
mobile-native. All post-hackathon; none blocks this pipeline.
