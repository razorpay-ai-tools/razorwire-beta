# Instagram for Razorpay — Feasibility, Design & 3-Day Build Plan

**Source idea:** `doc_r523noskel555f7f` (Team *Unrealistic Expectations* — Shivang, Sarthak, Saksham, Sambhav)
**Reviewed:** 2026-08-17

---

## 1. Verdict

**Buildable in 3 days — but not as scoped.** Three phases as written is three products. The
collapse that makes it fit: **Phase 2 and Phase 3 are the same pipeline with different inputs.**
Build one renderer, two thin ingest adapters. That turns a 3-product plan into a 1-product plan.

| Phase | As scoped | Verdict |
|---|---|---|
| 1 — Feed + upload | Own workstream | Feasible, ~6h, 1 person |
| 2 — Topic → video | Own pipeline | **Demote.** Same pipeline, ungrounded input |
| 3 — AIDoc → video | Stretch (storyboard only) | **Promote to the product.** Fully renderable |

**Reframe the pitch.** "Instagram for Razorpay" gets you judged on the feed — a weekend CRUD app.
The moat is doc → explainer. Lead with:

> **Every tech spec ships with a 60-second explainer. Automatically.**

The feed is the distribution surface, not the product.

---

## 2. Dependency reality check

The submission marks four dependencies TBD. Three are already resolved:

| Dependency | Doc says | Actual |
|---|---|---|
| AIDocs API | requested / TBD | **RESOLVED.** `aidocs` CLI works today (verified). `aidocs docs pull <id> --out f.html`. MCP at `<host>/mcp`. Service-account bearer tokens exist for headless. |
| Object storage | TBD | **RESOLVED.** S3 + presigned PUT. Razorpay has AWS. |
| SSO / auth | TBD → mock login | **RESOLVED.** Google OAuth via NextAuth, `hd` restricted to `razorpay.com`. ~20 lines. Kill the "mock login" weakness. |
| TTS + video assembly | TBD | **The only real unknown.** See §4. |

Rewrite the dependency section before screening. "Requested/TBD" reads as unstarted; "verified working" reads as de-risked.

---

## 3. Competitive reality — read this before you pitch

**Google shipped your Phase 3 seven weeks ago.** NotebookLM *Short Video Overviews* (announced
2026-06-30, GA to web July 2026): upload sources → ~60s **vertical 9:16** narrated video, grounded
in your material. Google's own framing: *"doom scrolling, but make it educational."*

Do not pretend this doesn't exist. A judge will raise it. Turn it into the strongest slide you have:

| | NotebookLM SVO | This |
|---|---|---|
| Data boundary | Sources leave the perimeter | Internal only, self-hosted render |
| Visuals | Nano-Banana AI *imagery* — decorative | **Real Mermaid architecture diagrams from the doc** |
| Source awareness | Generic text | AIDoc-native: parses current-vs-proposed sections |
| Trigger | Human pulls, one doc at a time | **Push — auto-generates on doc publish** |
| Surface | Private notebook | Shared org feed + watch analytics |

**The killer line:** NotebookLM draws a pretty picture next to your architecture. We draw *your
architecture*. For a payments company reviewing UPI mandate flows, decorative ≠ useful.

Everything else in the market is avatar/slide-fidelity tooling (HeyGen, Synthesia, SlideSpeak,
Colossyan) — SaaS, external data egress, no diagram accuracy, no internal corpus. Not competitors
for confidential specs.

---

## 4. High-level design

### 4.1 One pipeline, two mouths

```
┌── ingest ─────────┐
│ AIDoc (aidocs CLI)│──┐
│ Topic / raw text  │──┤
└───────────────────┘  │
                       v
        ┌──────────────────────────────┐
        │ 1. NORMALISE  html → sections│
        │ 2. SCRIPT     Claude → JSON  │  ← storyboard.json = THE CONTRACT
        │ 3. VOICE      TTS per scene  │  ← returns real durations
        │ 4. VISUALS    mermaid → SVG  │  ← validate; downgrade on fail
        │ 5. RENDER     Remotion → MP4 │
        │ 6. PUBLISH    S3 + DB row    │
        └──────────────────────────────┘
                       │
                       v
              vertical feed (web)
```

### 4.2 The storyboard contract — freeze this in hour 2

Everything else is parallelisable once this is frozen. **The LLM does not set durations.**

```jsonc
{
  "meta": { "title": "OTM/SBMD Rearch in 60s", "tags": ["upi"], "aspect": "9:16", "fps": 30 },
  "source": { "kind": "aidoc", "docId": "doc_r523...", "url": "..." },
  "scenes": [
    { "type": "title",   "heading": "...", "sub": "...",            "narration": "..." },
    { "type": "bullets", "heading": "...", "bullets": ["a","b"],    "narration": "...", "cite": "§2 Problem" },
    { "type": "diagram", "heading": "...", "mermaid": "graph LR; A-->B", "narration": "...", "cite": "§4" },
    { "type": "compare", "left": {...}, "right": {...},            "narration": "...", "cite": "§4.1" },
    { "type": "code",    "lang": "go", "code": "...",              "narration": "..." },
    { "type": "outro",   "cta": "Read the full doc", "url": "..." }
  ]
}
```

**Why no `durationMs` from the LLM:** scene length = length of its TTS audio, measured after step 3.
Kills an entire class of audio/visual desync bugs for free. 6 scene types is the cap — resist a 7th.

**`cite` is a differentiator, not decoration.** Render it as a chip on-screen ("§4 Proposed
Architecture"). It answers "is this hallucinating?" before a judge asks.

### 4.3 Captions without forced alignment

Split each scene's narration into sentences, allocate scene time proportional to character count.
No Whisper, no alignment library, no extra model.

```
// ponytail: proportional-by-charcount caption timing. Swap for whisper-timestamped
// word alignment only if a judge notices drift — at 1 sentence/3s nobody will.
```

### 4.4 API surface — 6 endpoints, no more

```
POST /api/upload                → presigned S3 PUT + video row      (Phase 1)
GET  /api/feed?cursor=          → paginated feed
POST /api/generate              → { kind:"aidoc"|"topic", input } → jobId
GET  /api/jobs/:id              → { state, progress, videoId }     (poll 1s)
POST /api/videos/:id/view       → view counter
GET  /api/videos/:id/storyboard → judge-facing grounding view
```

`jobs.state`: `queued → scripting → voicing → rendering → published | failed`
Show these as live steps in the UI. A visible pipeline *is* the demo during the 90s render wait.

### 4.5 Data model — two tables

```sql
videos(id, title, tags, author, src_url, thumb_url, duration_ms,
       kind, source_doc_id, storyboard_json, views, created_at)
jobs(id, state, progress, error, video_id, created_at)
```

SQLite via Drizzle. Zero infra. Migrate to Postgres post-hackathon, not before.

---

## 5. Stack

| Layer | Pick | Why |
|---|---|---|
| App | **Next.js 16** (App Router), single repo | UI + API in one deploy. Renderer must be Node anyway — a separate Go service buys nothing but a boundary. Note: Next 16 has breaking changes vs training data — read `node_modules/next/dist/docs/`. |
| Feed UI | CSS `scroll-snap-type: y mandatory` + `<video>` | Native. No carousel library. |
| DB | SQLite + Drizzle | One file. No container. |
| Storage | S3 presigned PUT | No upload proxying through the app. |
| Auth | NextAuth Google, `hd=razorpay.com` | Real SSO in ~20 lines. |
| Script LLM | **Claude Sonnet 5**, tool-call structured output | Fast + cheap; schema-validated with one retry. Escalate to Opus 5 only if quality misses. |
| Diagrams | **Mermaid** (MIT), rendered in-page | Claude already writes fluent Mermaid. Cap at 7 nodes. |
| TTS | **ElevenLabs** for demo · **Kokoro-82M** (Apache-2.0, ~327MB, CPU, 54 voices) for the "no egress" answer | Have both. See §6 licensing/egress. |
| Footage | **Google Veo 3.1** — pre-generated b-roll library, mood-keyed | Makes the feed look like video instead of a slide deck. Never carries information. See §5.5. |
| Video | **Remotion** (React → MP4), Veo clip as background layer | Team knows React. Scenes are components. Deterministic overlay on top of generative footage — the documented correct split. |
| Job queue | In-process array + `setInterval` worker | 4 users, 1 box. |
| Deploy | One EC2/dev box + **QR code on screen** | Judges scroll the feed on their own phones. Cheapest memorable moment in the demo. |

### Rejected, deliberately

- **Generative video as the information layer** — see §5.5. Veo is in, but only as a background plate.
- **Avatar platforms (HeyGen/Synthesia)** — SaaS, egress, no diagram accuracy.
- **Manim** — beautiful, slow, steep. Not in 3 days.
- **HLS / transcoding / CDN** — MP4 + HTTP range requests. Fine for 20 videos.
- **Recommendation feed, moderation, mobile-native** — already out of scope in the doc. Keep it that way.

---

## 5.5 Google Veo — where it goes, and where it must not

**Decision: Veo is in, as the background layer only. It never carries information.**

This is not a hedge. It is the documented industry mitigation for the one thing generative
video reliably fails at.

### The constraint

Veo 3 and 3.1 **cannot render legible text or an accurate diagram.** This is a known,
unresolved limitation of the architecture, not a prompting problem — signs, labels and
callouts come out blurred or misspelled. Veo 3 is also notorious for hallucinating garbled
subtitles even when the prompt forbids captions; one creator measured ~40% of dialogue clips
unusable for that reason.

Point Veo at "a diagram showing pg-router calling payments-mandate" and you get something that
looks like an architecture diagram and says nothing. For a spec explainer that is worse than
useless — it is confidently wrong, which is the exact failure mode our citation feature exists
to rule out. It would also delete the differentiation in §3: *we draw your architecture.*

The standard pipeline everywhere this is done well: **generate footage as a clean plate,
composite text and diagrams in post.** So:

| Layer | Who renders it | Why |
|---|---|---|
| Background footage | **Veo** | Motion, texture, production feel |
| Diagram, bullets, code, labels, captions, cite chip | **Remotion / DOM** | Must be exact and legible |

### The design: mood-keyed, pre-generated, cached

Claude never writes a Veo prompt. It picks a `mood` from a closed enum:

```
dataflow · servers · team · money · abstract · city
```

A resolver maps mood → a clip from a library we generate **once**, from hand-written prompts
containing no spec content. Implemented in `src/lib/storyboard.ts`; `broll.clipId` is
pipeline-owned and the validator rejects a model that tries to set it.

Three consequences, all of which matter more than they look:

1. **No spec content ever reaches a video prompt.** The egress objection disappears for the
   video layer entirely — the prompts are generic and human-written.
2. **No generation latency on the request path.** Veo takes 1–2 min per 8s clip. Generating
   per-request would put 8 sequential generations in front of the user. Selecting from cache is
   instant.
3. **No cost surprise.** Fixed one-time spend instead of per-view cost.

### Cost

Veo 3.1 caps at 8s per generation (4/6/8s, 24fps, 9:16 supported), so longer needs chaining.
Published per-second rates vary widely by tier and source — roughly $0.05/s (Lite) to $0.40/s
(Standard), with resellers quoting up to $0.75/s. **Verify on Google's own pricing page before
budgeting.** Generate with audio disabled: we have our own narration, it is cheaper, and it
avoids the garbled-subtitle problem.

```
Library of 15 clips × 8s
  at Lite     ~$0.05/s  →  ~$6    one-time
  at Fast     ~$0.15/s  →  ~$18   one-time
  at Standard ~$0.40/s  →  ~$48   one-time
```

A ~$6–18 one-time spend, on a new GCP project's $300 free credit. Build the library on Day 1
and the cost question never comes up again.

### One live-generation moment

Keep a single **"generate culture reel with Veo"** button on the topic path, where accuracy does
not matter and a 90-second wait is acceptable. It shows real generative video on stage without
putting it anywhere near a tech spec. Have a pre-generated one on disk as backup.

> **Day 0 addition:** GCP project + Vertex AI / Gemini API access for Veo, and confirm the
> per-second rate for the tier we pick. Default rate limit is ~10 req/min, which is fine for
> building a library and useless for per-request generation — another reason to cache.

---

## 5.6 Revision after reading the razorwire boilerplate

The existing prototype changed one of my earlier recommendations. Recording it so the reasoning
is not lost:

**The browser reel player becomes the primary surface. MP4 becomes an export.**

Razorwire already plays a storyboard as a scene sequence with `SpeechSynthesis` narration, with
zero render latency. That is a better *demo* artifact than an MP4:

- Generation completes in seconds, not ~2 minutes, so the claim gets **stronger**, not weaker.
- It removes render time — previously the top risk — from the critical path.
- The Remotion licence question stops being a blocker and becomes an export-path question.
- Browser TTS means **zero egress for voice** on the default path, for free.

MP4 export is then generated lazily, off the request path, for sharing into Slack. Pre-render
the demo doc's MP4 so render latency never appears on stage.

What the prototype is missing is exactly the three things that make the pitch true: real
diagrams, citations, and actual AI. Those are the work. The shell is done.

---

## 6. Two flags to resolve on Day 0 (30 minutes)

**1. Remotion licensing.** Source-available, *not* OSI open source. Free only for individuals or
for-profits with ≤3 employees. Razorpay needs a Company License: **Automators tier $0.01/render,
$100/mo minimum**. The evaluation clause covers a hackathon, but get it in writing from whoever owns
OSS approval before you build on it. Remotion 5.0 changes the license — check `LICENSE.md`.

- **MIT fallback:** **Motion Canvas** (MIT) or Playwright-screenshot-each-frame + `ffmpeg` concat.
  The ffmpeg path is ~150 lines of glue and zero license risk. Have it identified, don't build it.

**2. Data egress.** Sending spec text to ElevenLabs/OpenAI TTS = confidential content leaving the
perimeter. At a payments company this question *will* be asked.

- Demo with a **non-sensitive sample spec** and say so out loud.
- Name **Kokoro-82M running locally** as the production answer. Open-weight TTS closed most of the
  gap to commercial in 2026 (223 → 81 ELO on Speech Arena). Have it installed as a live fallback,
  not a slide.

---

## 7. Three-day plan

Assume ~10h/day, 4 people. **Every day ends with something demoable.** Nothing is left "half-wired
overnight."

### Day 0 — pre-work, tonight (2h, do not skip)

- [ ] Repo scaffolded, Next.js + Drizzle + S3 bucket + `.env` shared
- [ ] Claude API key, ElevenLabs key, **aidocs service-account token** all verified with one curl each
- [ ] `npx remotion@latest studio` renders the starter template on every laptop (proves ffmpeg/Chromium)
- [ ] Remotion license question sent to whoever answers it
- [ ] Pick the sample AIDoc (non-sensitive, has current + proposed architecture)

### Day 1 — contract, then parallel

| Hours | Work | Owner |
|---|---|---|
| 0–2 | **Freeze `storyboard.json` schema + JSON Schema file.** Whole team, one room. Nothing starts before this. | all |
| 2–6 | Feed UI: scroll-snap vertical player, autoplay-on-view, mute toggle | Saksham |
| 2–6 | Upload: presigned PUT, title/tags form, thumbnail via `<canvas>` frame grab | Sambhav |
| 2–6 | Remotion: 6 scene components against a **hand-written** storyboard fixture | Sarthak |
| 2–6 | Ingest: `aidocs docs pull` → sections; Claude prompt → storyboard; schema validate + retry | Shivang |
| 6–10 | Wire + Google OAuth. **Checkpoint 1: upload → feed → play, live.** | all |

**Gate:** if Checkpoint 1 slips past Day 1, cut the topic→video path entirely tomorrow morning.

### Day 2 — the pipeline (this is the risk day)

| Hours | Work |
|---|---|
| 0–4 | **Checkpoint 2 (hard deadline, Day 2 noon): fixture storyboard → rendered MP4 with audio.** No LLM in the loop. If this misses noon, switch to the Playwright+ffmpeg fallback immediately — do not debug Remotion past noon. |
| 4–7 | TTS per scene → durations → inject → captions. Job queue + live progress UI. **Checkpoint 3: text → published video, end to end.** |
| 7–10 | AIDoc path: real doc → storyboard → MP4. **Checkpoint 4: Phase 3 working, unpolished.** |

### Day 3 — quality, then stop

| Hours | Work |
|---|---|
| 0–4 | Mermaid diagram scenes + `compare` scene (current vs proposed). `cite` chips. Typography and motion polish. |
| 4–6 | **FEATURE FREEZE at hour 6.** Anything broken gets cut, not fixed. |
| 4–6 | Seed the feed with 8–10 real videos (team clips + 4 generated). An empty feed kills the demo. |
| 6–8 | **Pre-render 3 backup MP4s** of the exact demo doc. Rehearse the demo 3× on the real network. QR code printed. |
| 8–10 | Buffer. Do not add features with buffer time. |

---

## 8. Risk register

| Risk | Sev | Mitigation |
|---|---|---|
| Render exceeds 2 min | ~~High~~ **Low** | **Downgraded.** The browser reel is now the primary surface (§5.6), so MP4 render is off the request path. 720×1280, 30fps, cap 8 scenes, pre-rendered backups still apply to the export. |
| Veo used for a diagram or any legible text | **High** | Structural, not procedural: Claude only picks a `mood` from an enum, and the validator rejects a model-set `clipId`. Diagram, bullets and code are DOM/Remotion layers composited *over* the plate. |
| Veo latency or rate limit on stage | Med | Library pre-generated on Day 1, never per-request. The one live-generation button has a pre-generated backup on disk. |
| Mermaid overflows / unreadable | **High** | Cap 7 nodes in the prompt. Headless-validate the SVG; on failure or overflow, auto-downgrade the scene to `bullets`. Never ship a broken diagram. |
| LLM returns invalid storyboard | Med | Tool-call structured output + JSON Schema validate + 1 retry + fixture fallback. |
| Remotion license blocks it | Med | Day 0 question. ffmpeg fallback identified. |
| Wifi dies during live demo | Med | Localhost + local S3 mock + pre-rendered MP4s in `public/`. |
| Autoplay blocked by browser | Low | Muted autoplay + explicit unmute button. Test in Safari, not just Chrome. |
| Narration/visual desync | Low | Durations derived from audio, never authored. Structurally prevented. |

---

## 9. Rewrite the three claims

Current claim 3 promises a *storyboard*. With the unified pipeline you can promise the video.

1. A Razorpay employee signs in with Google SSO, uploads a byte-sized video, and it plays in a
   scrollable vertical feed on a judge's own phone — live.
2. Paste an internal **AIDoc URL** → a 60-second narrated, captioned explainer with the doc's real
   architecture diagram is generated and published to the feed in under 2 minutes — live.
3. Every scene carries a **source citation** back to the doc section it came from, so any claim in
   the video is checkable against the spec — no hallucinated architecture.

Claim 3 is the one nobody else in the room will have.

---

## 10. The validation gap — 30 minutes, cheapest points available

The submission flags this honestly, which is good, but it's fixable before screening:

- **aidocs view analytics** — you have CLI/MCP access. Pull: docs published last quarter, unique
  viewers per doc, median time-on-doc.
- **One 4-question Slack poll** in 3 team channels: "last tech spec you were asked to read — did you
  read it fully / skim / not at all?"
- Get **one hard number** on the slide. "N specs published last quarter, median read-through X%" beats
  a paragraph of narrative pain.

**Claim reach, not retention.** You cannot prove video teaches better in 3 days. You *can* prove
distribution: "this spec was read by 12 people; the explainer was watched by 80." Instrument views on
Day 1 and that number is real by demo day.

---

## 11. Post-hackathon, one slide

- **The push trigger:** aidocs webhook on publish → explainer auto-generated, no human ask. This is
  the actual product; the hackathon proves the pipeline.
- Slack unfurl: paste an aidoc link, get the 60s video inline.
- Kokoro on-prem = zero egress, unlimited volume, ~$0 marginal cost.
- Onboarding playlists auto-built per team from that team's specs.

---

## Sources

- [Remotion Company Licensing](https://www.remotion.pro/license) · [License FAQ](https://www.remotion.dev/docs/license/faq)
- [Best Open-Source TTS Models 2026 (BentoML)](https://www.bentoml.com/blog/exploring-the-world-of-open-source-text-to-speech-models) · [Kokoro Local Setup](https://localaimaster.com/blog/kokoro-tts-local-setup)
- [NotebookLM Short Video Overviews alternatives (Pexo)](https://pexo.ai/blog/notebooklm-short-video-overviews-alternatives-8099) · [Document→video tools 2026](https://docustream.ai/7-best-ai-tools-to-turn-documents-into-videos-2026-review/)
