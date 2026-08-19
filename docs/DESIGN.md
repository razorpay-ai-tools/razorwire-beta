# Razorwire — Design, validated

Review of the first design pass against `backend/app/storyboard.py` (the contract) and
the running API. **The visual direction was kept**: glassmorphism panels over a dual
scrim is the right answer for text on moving video, and the Storyboard Inspector was a
genuinely good addition nobody asked for. Fifteen things needed correcting.

---

## 1. What was wrong

### Would not have rendered at all

| # | Issue | Fix |
|---|---|---|
| 1 | `text-brand-400` used by the citation chip; token map stopped at `brand-500` | Full brand ramp 300–700 |
| 2 | `animate-fade-in` used by the caption bar; never declared | `--animate-fade-in` + `@keyframes` |
| 3 | Partial `neutral` ramp (950/900/800/700/400/100 only) silently overrides Tailwind's built-in, so `neutral-600`, `-500`, `-300`, `-200` resolve to stock values and the palette drifts | Full ramp 50–950 |
| 4 | Progress bar spec combined `h-1.5` with `pt-3 pb-1` — 6px tall with 16px of vertical padding is unsatisfiable | Padding on the wrapper, height on the track |

### Contradicted the contract

| # | Issue | Fix |
|---|---|---|
| 5 | Citation chip on the `title` scene. The contract requires `cite` on `bullets`/`diagram`/`compare`/`code` only — `title` and `outro` assert no fact and have none. A chip there **invents a citation**, which is precisely the failure the feature exists to disprove | Chip renders only when `scene.cite` exists |
| 6 | Two conflicting scrim recipes (`via-neutral-950/40` in tokens, `via-transparent` in the component) | One recipe, two weights: `scrim-light` for title/outro, `scrim-heavy` for dense scenes. `scrimFor()` picks |

### Wrong about the product

| # | Issue | Fix |
|---|---|---|
| 7 | **"Paste a Notion, Confluence, or GitHub spec URL"** and `confluence.razorpay.com`. Our only ingestion source is **aidocs** — that integration *is* the differentiator | aidocs URL / `doc_...` id |
| 8 | Pipeline stepper showed 4 invented steps. Real states: `queued → scripting → voicing → rendering → published \| failed`, and the default browser-reel path is only `queued → scripting → published` | Conditional steps; two permanently dead rows read as broken |
| 9 | **No `failed` state designed at all** — yet the pipeline retries 3× feeding validation errors back to the model and can still give up | Designed, with `job.error` surfaced and Retry |
| 10 | "Target Audience: All Tech / New Joiners" — invented, no such API field | Dropped |

### Missing

| # | Issue | Fix |
|---|---|---|
| 11 | **`clip` posts were not designed.** Roughly half the feed is uploaded team video with no scenes, no citations, no captions. The design assumed every post was a storyboard | Two explicit variants, deliberately distinct |
| 12 | `post.currentCitation`, `post.currentCaption`, `post.videoUrl`, `post.commentsCount` do not exist on the API. Current scene and caption are **client** state | `src/lib/api.ts` mirrors the real response; `useReel` owns scene state |
| 13 | View count absent from the feed, though reach is the metric the whole pitch rests on | Surfaced in the metadata block |
| 14 | Emoji as the entire action rail. Double-width, unrecolourable, reads as "Unicode character" to a screen reader — and it is why the original ASCII frames were misaligned | Inline SVG `Icon` with a required label |
| 15 | Light mode absent despite being requested | **Accepted as dark-only, deliberately.** The feed is full-bleed video; a light theme would apply to two screens. Not worth it in three days. Now a decision, not an omission |

---

## 2. Tokens

Live in `src/app/globals.css`. Custom utilities available:

```
scrim-light   scrim-heavy   panel   scene-safe
animate-fade-in   animate-pulse-ring
```

`prefers-reduced-motion` neutralises all animation globally. Focus-visible rings are
applied to every interactive element via a `:where()` rule.

---

## 3. The feed — the focus screen

Two variants. The difference is the point: a clip must not look like a generated post
that failed to load.

### 3a. Generated post — storyboard plays as a scene sequence

```
+--------------------------------------+
| ####  ####  ####  ----  ----  ----   |
|                                      |
|  ARCHITECTURE                        |
|                                      |
|                                (b)   |
|   The rearch path                    |
|                                248   |
|      +-------------+                 |
|      |    Edge     |           (c)   |
|      +------+------+                 |
|             |                   19   |
|             v                        |
|      +-------------+           (s)   |
|      |  pg-router  |                 |
|      +------+------+          Save   |
|             |                        |
|             v                  (d)   |
|      +-------------+                 |
|      |     CPS     |          Spec   |
|      +-------------+                 |
|                                      |
|  { doc  S 4.1 - Request Flow }       |
|                                      |
|  (SJ) sambhav.jain  .  upi-core      |
|  UPI One-Time Mandates, rearchi...   |
|  1.2k views  .  6 scenes  .  58s     |
|  +--------------------------------+  |
|  | "pg-router evaluates a Splitz  |  |
|  |  experiment to decide rearch." |  |
|  +--------------------------------+  |
+--------------------------------------+
```

| Region | Element |
|---|---|
| Row 1 | Scene progress — one segment per scene, 3 of 6 elapsed |
| Row 3 | Category chip |
| Right rail | `(b)` like · `(c)` comment · `(s)` save · `(d)` Spec, with counts |
| Centre | `SceneView` renders the active scene — here a `diagram` |
| Above metadata | Citation chip for the active scene |
| Metadata | Avatar initials, author, team, title, **view count** |
| Bottom panel | Caption bar, one sentence of narration at a time |

- Background is the scene's Veo b-roll, `object-cover`, muted, looped. On 404 it falls
  back to an accent gradient — never a black void.
- Scrim weight comes from the scene type, so a diagram gets a heavier plate than a
  title card.
- Tap the left/right third to step scenes. Arrow keys do the same. `m` toggles mute.
- Only the active post plays; every other video and timer is paused.

### 3b. Clip post — a single uploaded video

```
+--------------------------------------+
|                                      |
|  CULTURE                             |
|                                      |
|                                (b)   |
|                                      |
|                                 92   |
|        [ uploaded video,             |
|          full bleed,           (c)   |
|          no scenes,                  |
|          no citation,            7   |
|          no captions ]               |
|                                (s)   |
|                                      |
|                               Save   |
|                                      |
|                                      |
|                                      |
|  ---------------o------------------  |
|  0:24 / 0:58                         |
|                                      |
|  (SG) saksham.garg  .  design-sys    |
|  How we run design crit              |
|  340 views                           |
+--------------------------------------+
```

Four deliberate absences, each one a signal that this is a different kind of post:

| Absent | Why |
|---|---|
| Scene progress segments | There are no scenes — a scrub position bar replaces them |
| Citation chip | Nothing was generated from a document, so nothing to cite |
| Caption bar | No narration script exists for an uploaded clip |
| `Spec` action | No source document to open |

### 3c. Desktop

The 9:16 player centres in a `max-w-md` frame on a neutral-950 backdrop, with the
Storyboard Inspector docked as a `md:w-96` side panel so narration and citations can be
audited against the spec while the video plays.

---

## 4. Scene templates

All six render inside `scene-safe` (top 8%, bottom 12%), assume a 360px-wide viewport,
and assume arbitrary moving video behind every pixel.

- **title** — heading + optional sub, centred, most breathing room. No chip.
- **bullets** — heading + 2–5 phrases, staggered entry. Phrases are read by the eye and
  must not duplicate the narration.
- **diagram** — real Mermaid, dark theme mapped to our tokens, bounded height. **On
  render failure it degrades to the heading plus a plain node list.** A viewer never
  sees a broken diagram or an error string. The 7-node cap in the contract exists so
  this fits.
- **compare** — direction of change must be obvious. Two 4-item columns at 360px is too
  tight, so this stacks with a divider rather than pretending it fits.
- **code** — ≤12 lines, monospace, horizontally scrollable rather than wrapped. No
  syntax-highlighting dependency; legibility beats colour.
- **outro** — `cta` as a brand-filled primary action, `rel="noopener noreferrer"`. No chip.

---

## 5. Pipeline stepper

Steps are conditional on the path actually taken, and the terminal failure is designed:

```
Default (browser reel, ~10s)      With MP4 export
  [x] queued                        [x] queued
  [~] scripting                     [x] scripting
  [ ] published                     [~] voicing
                                    [ ] rendering
                                    [ ] published
```

On `failed`, `job.error` is shown in readable form with a Retry. When the error names
the diagram node cap or a missing citation, the copy says the guardrail rejected the
output — that is the system working, and worth showing a judge.

---

## 6. Accessibility floor

Not optional, and cheap at this size:

- Every icon button has an accessible name; icons are SVG, never emoji.
- Colour is never the only signal.
- Captions are burned in because most viewing is muted.
- Video is muted by default with one obvious unmute control (browsers block unmuted
  autoplay regardless).
- Keyboard reaches every control, with a visible focus ring.
- `prefers-reduced-motion` is respected globally.
