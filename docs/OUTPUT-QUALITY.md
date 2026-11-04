# Making the output good — free tools, ranked by what they actually buy us

Five of these are shipped. The rest are researched, costed and ordered; nothing below
needs a paid licence.

---

## Shipped

### 1. Loudness normalisation — EBU R128, two-pass ffmpeg

`backend/app/render/qa.py`, on by default (`RENDER_QA=true`).

**The defect it fixes is real and was measured, not theorised.** The sample reel came
out at **-22.5 LUFS** — 6.5 LU under target, quiet enough that a viewer reaches for the
volume, and every reel drifts differently because scene audio comes from whichever TTS
backend was available (Kokoro at one level, macOS `say` at another). A feed where one
post is quiet and the next is loud reads as broken.

Now normalised to **-16 LUFS, -1.5 dBTP**. Two passes, not one: a single pass only
*estimates* the input and lands within about 1 LU of target — which is exactly the
drift that makes two reels sound different. Video stream is copied, so only audio is
re-encoded.

Three gotchas that are encoded in the module rather than left as folklore:

- **Never 0 dBTP.** AAC generates intersample peaks on decode that exceed the encoded
  peak by 1–3 dB; a 0 dBTP master clips on some decoders.
- **Skip silence.** True digital silence measures `-inf` (ffmpeg's gate floors at -70
  LUFS). Normalising it just amplifies hiss.
- **Skip what is already on target.** The filter is not a no-op — it still resamples
  and re-encodes.

Dynamic mode, not `linear=true`: this is speech. Linear applies one constant gain,
which suits music and leaves a quiet scene quiet.

### 2. Render QA detectors — black / silent / frozen / length

Same module. Catches the class of failure where **ffmpeg exits 0 and the job publishes
a black rectangle**: a scene that never signalled ready and screenshotted a blank page,
a wav that came back as digital silence, a filtergraph that held one frame.

Findings are logged, never fatal — a reel with a short black run is still a reel, and a
human reading the job log is a better judge than a threshold.

One threshold is non-obvious and worth keeping: **`freezedetect` is derived from the
reel's own length**, not fixed at the usual `d=2.0`. A razorwire scene *is* a held
frame — the ffmpeg engine renders most scenes as one still. At 2 s every scene of every
reel is a finding, i.e. a detector that only cries wolf. At 90 % of duration it fires on
exactly one thing: a reel where nothing moved at all.

Verified both ways — clean on the real reel, all four findings on a synthesised
black/silent file.

### 3. Poster frames — every generated post had a black thumbnail

`backend/app/render/poster.py`.

Measured, not suspected: **frame 0 is luma 5.9 on the composition engine and luma 0 on
the ffmpeg engine.** Both open on a fade from black — `compose.OPEN_FADE_S` on one, a
plate tweened up from `opacity: 0` on the other — and `publish._create_post` was setting
`thumbnail_url=None` with the comment *"the `<video>` uses its first frame as the
poster"*. So it did. Every generated post in the feed was a black tile.

Two halves to the fix, and both are needed:

- **Pick a real frame.** Candidates are ranked by scene *type*, not position: a diagram
  first, an outro never. Every reel's title card looks like every other reel's title
  card; the architecture diagram is the frame that says what *this* post is. Sampled at
  75 % through the scene, past the build-up. Each candidate is luma-checked and the
  first bright one wins, so a short scene still fading in is skipped rather than
  reasoned about.
- **Bake it as frame 0.** A bare MP4 has no `poster` attribute, and Slack, Twitter and
  Discord regenerate thumbnails server-side and ignore embedded cover art. Overlaying
  the poster onto frame 0 is the only thing that controls the idle image everywhere. At
  30 fps it shows for 1/30 s — imperceptible on playback, and exactly what a thumbnail
  grabber takes.

The JPG is stored alongside the MP4 and set as `thumbnail_url`. No frontend change was
needed: `ClipPost`, `DesktopCard` and `GeneratedPost` already pass
`poster={post.thumbnailUrl ?? undefined}` — the value was simply always null.

End-to-end on the sample reel: frame 0 went **5.86 → 35.16**, poster taken from the
architecture-diagram scene at 43.1 s, duration and audio unchanged.

One accepted wart: cues are stretched to be gapless, so every frame carries a subtitle
and the poster inherits a mid-sentence fragment. It reads as a subtitle on a video,
which is what it is — not worth engineering around.

### 4. GSAP's premium plugins — free since 3.13, and two of them earn their place

Webflow acquired GreenSock and made the whole of GSAP free in April 2025, including
commercial use. The Club-only plugins went into the public npm package with 3.13, so
`DrawSVGPlugin` and `SplitText` are now a plain dependency rather than a licence
question. Installed as a devDependency and **vendored out of `node_modules`** into the
composition, alongside mermaid — a render that needs the network to draw a diagram is
a render that fails on a bad day for no reason.

**DrawSVG on the Mermaid connectors.** Edges now draw along their own length instead
of fading in. It costs nothing in fidelity: it is still the doc's real Mermaid SVG,
just revealed the way a person would draw it.

That change surfaced a bug worth recording. A `marker-end` arrowhead is painted at the
path's *geometric* end no matter how little stroke is currently visible, so every
not-yet-drawn edge showed a disembodied arrowhead floating in open space above its own
line. Scheduling the marker's removal for the moment the draw begins is too late — the
stroke sits at 0% length from frame one. It has to come off synchronously when the
diagram is wired, and go back on with a timeline `set` once the stroke arrives (a `set`
rather than an `onComplete`, so it survives seeking). There is a regression test.

**SplitText on the headings.** Headings arrive a word at a time, masked per line so
each word slides out from behind its own baseline rather than floating up through the
frame. Both plugins degrade to a plain fade if they are ever missing — a missing plugin
should cost polish, never the scene.

Verified in the DOM rather than by eye: both plugins load, the heading becomes 5 nested
word/line nodes instead of a text node, and all 5 edges carry `marker-end="none"` plus
a DrawSVG-managed `stroke-dasharray`.

Applies to the composition engine only — which is now the **default**, so this is what
a generation produces unless `RENDER_ENGINE=ffmpeg` says otherwise. The ffmpeg engine
still fades and cannot do better: it has stills to cross-fade, not elements to animate.

### 5. The Hyperframes registry — 382 blocks, already local

`npx hyperframes catalog --query "<the move, in English>"` searches on-disk with no
account and nothing sent anywhere. Directly relevant hits: `flowchart-vertical` (a
portrait animated decision tree with SVG connectors), `hw-pipeline` (wobbled boxes with
handwritten labels drawing on in sequence), `constellation-hub`, `animated-bar-chart`,
`data-chart`.

**Deliberately not used for the diagram scene.** RazorWire's claim is that the
architecture in the reel *is* the architecture in the doc. Swapping the real Mermaid
render for a prettier stock flowchart would buy visual polish by giving up the one
property that makes the reel trustworthy. These blocks are worth reaching for if a
storyboard ever gains a scene type with no source diagram behind it — a stat card, a
chart — where there is nothing to be unfaithful to.

---

## Worth doing next

### 6. b-roll — the one parity gap

The ffmpeg engine composites scenes over `<mood>.mp4` from `broll_dir`; the composition
engine currently uses the mood gradient only. Two free routes, and they are not
equivalent:

**Pre-generate the mood library locally with Wan 2.2 (Apache 2.0).** There are six
moods. Generate each clip once, offline, commit it, done. Wan 2.2's 5B variant runs in
8 GB VRAM and takes ~4–6 min for a 5-second 480p clip on a 4090 — far too slow inside a
~10-second job, and completely fine as a one-off. Wan is the cleanest licence of the
open-weight video models: Apache 2.0, and Alibaba claims no rights over generated
output. Avoid LTX (free commercial use only under ~$10M revenue) and HunyuanVideo (its
licence territory *excludes* the EU/UK/South Korea).

**Or pull from the Pexels API at generation time.** Free, commercial use, no attribution
required. But note what this actually does: **it sends a query derived from an internal
tech spec to a third party on every render.** The mood enum is generic today
(`dataflow`, `servers`, `money`), so the leak is small — but if scene keywords ever
drive the query, that is doc content leaving the network from a tool whose whole premise
is internal documents. The local pre-generated library has no such property.

Recommendation: **pre-generate locally.** It is a fixed six-clip cost, it keeps the
privacy story intact, and it removes a network dependency from the render path.

### 7. Caption-sync verification as a gate

We already have word-level timestamps free from Kokoro — it computes them for its own
vocoder and `tts.py` keeps the tokens instead of discarding them. What we have no check
on is whether the *rendered* audio matches them.

Since the script text is known, skip ASR-as-oracle and use forced alignment directly:
`ctc-forced-aligner` (MMS-300M) or WhisperX's align stage, then diff aligned word onsets
against the cue times and flag drift beyond ~100 ms. This also catches TTS dropouts and
insertions, which a pure timestamp comparison misses. Note `whisper.cpp` has **no**
built-in forced aligner — it is transcription only.

Worth it when a non-Kokoro backend is in play (`say` and silent both fall back to
*estimated* cues apportioned by character count, which is a guess).

### 8. Music bed — vendor a small CC0 set, don't wire an API

Jamendo is the only real free API with streamable audio (35k requests/month), but every
track carries its own Creative Commons terms — some commercial, some not, some
share-alike — and commercial use goes through separate Jamendo Licensing. That is
per-track legal review inside a render loop.

Uppbeat has the cleanest licence but no public API. Free Music Archive is CC 4.0 with
per-track variation.

For six-ish beds, an API is the wrong shape entirely: pick a handful of CC0 tracks by
hand, vendor them, save the licence certificate alongside each one. `RENDER_MUSIC_BED`
already accepts a path. (Save the certificate regardless — copyright claims on free
music are usually Content ID matches, not strikes, and you dispute them with the
licence you downloaded.)

### 9. TTS — Kokoro is still the right default

Worth stating so nobody re-litigates it. Kokoro-82M is the consensus best default
open-source TTS: Apache 2.0, 82 M params, CPU-capable, and it topped the TTS Arena.

The one model that would plausibly beat it is **Chatterbox** (MIT, 0.5 B) — Resemble's
own blind study had 65.3 % preferring it over ElevenLabs vs 24.5 %, though that study
was vendor-run. It also adds voice cloning from ~5 s, which we have no use for. Avoid
F5-TTS entirely: CC-BY-NC, non-commercial.

Verdict: not now. The win is small and the cost is a second model in the image.

### 10. Diagrams — Mermaid stays

D2 lays out complex architecture graphs better (TALA), has cleaner container syntax for
VPC/boundary nesting, and renders browser-free from Go. But Mermaid renders natively in
aidocs, GitHub and Notion — which matters because **the diagram in the reel is supposed
to be the diagram in the doc**. Switching renderers breaks that correspondence, and it
is the thing that makes the reel trustworthy.

Revisit only if specs start carrying 20+ node diagrams, where Mermaid's dagre layout
genuinely struggles. Note TALA, D2's good layout engine, needs a paid licence.

---

## Explicitly not worth it

- **VMAF / PSNR / SSIM.** All three are full-reference — they need an original to
  compare against. We *are* the original; there is no source to diff a render against.
  Useful only if we start offering multiple encode ladders.
- **Chasing a second stock-footage provider.** Clearances, not licence text, are the
  real exposure: a free site rarely guarantees a model or property release for a
  recognisable face or logo, and automated selection cannot eyeball that.

---

## Sources

- [Best Open Source TTS Models in 2026 — Kokoro, Chatterbox, Fish Audio compared](https://www.tryspeakeasy.io/blog/open-source-text-to-speech-2026)
- [The Best Open-Source Text-to-Speech Models in 2026 — BentoML](https://www.bentoml.com/blog/exploring-the-world-of-open-source-text-to-speech-models)
- [Two-pass loudness normalization with FFmpeg loudnorm](https://dev.to/masonwritescode/two-pass-loudness-normalization-with-ffmpeg-loudnorm-the-right-way-1nm3)
- [FFmpeg loudnorm Filter: EBU R128 guide](https://dev.to/javidjamae/ffmpeg-loudnorm-filter-ebu-r128-loudness-normalization-guide-15d4)
- [Pexels licence](https://www.pexels.com/license/) · [Pexels API](https://www.pexels.com/api/)
- [Open-source no-reference video quality tools](https://www.forasoft.com/learn/video-quality/articles-vqm/open-source-no-reference-tools)
- [Netflix/vmaf](https://github.com/Netflix/vmaf)
- [WhisperX — word-level timestamps and forced alignment](https://github.com/m-bain/whisperx)
- [Best open-source AI video generation models 2026 — Thunder Compute](https://www.thundercompute.com/blog/best-open-source-ai-video-generation-models)
- [Local AI video generation: Wan 2.2 vs LTX-2 vs HunyuanVideo](https://localaimaster.com/blog/local-ai-video-generation)
- [Jamendo API](https://freeapihub.com/apis/jamendo-api) · [Free Music Archive](https://freemusicarchive.org/)
- [Mermaid vs D2 — comparing text-to-diagram tools](https://aaronjbecker.com/posts/mermaid-vs-d2-comparing-text-to-diagram-tools/)
- [Simple Icons](https://simpleicons.org/)
- [GSAP 3.13 release notes](https://gsap.com/blog/3-13/) · [Webflow makes GSAP 100% free](https://webflow.com/blog/gsap-becomes-free) · [GSAP is now completely free, even for commercial use](https://css-tricks.com/gsap-is-now-completely-free-even-for-commercial-use/)
