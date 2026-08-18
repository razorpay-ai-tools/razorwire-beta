# Razorwire

Razorwire is an internal reels-style learning surface for products, systems, culture, and AIDocs. Teams can post short explainers, and source-of-truth documents can be turned into playable reel drafts.

## What you can do

- Browse an Instagram-style internal learning feed.
- Like, save, comment on, and share feed posts.
- Post a team clip with title, owner, category, duration, tags, and key takeaway.
- Paste or upload an AIDoc/spec/topic and create a playable explainer draft.
- Preview the generated reel with scenes, captions, narration, play/pause, next/previous, and browser voice narration.
- Post the generated reel back into the feed.

## How video creation works today

Razorwire currently creates a **playable reel draft**, not a rendered MP4 file.

The flow is:

```text
AIDoc / spec text
→ scenes + captions + narration script
→ playable reel preview
→ post reel to feed
```

The reel preview includes scene progression, captions, narration text, and optional browser voice playback. Exporting the draft as an MP4/WebM is a natural next step.

## Try the sample AIDoc

A sample non-sensitive spec is included at:

```text
public/samples/payment-routing-readiness-aidoc.md
```

Fastest path:

1. Run the app.
2. Click **Load sample AIDoc** in the **Generate from AIDoc** panel.
3. Click **Create reel draft**.
4. Press **Play** in the reel preview, or **Voice** to hear the current scene narrated by the browser.
5. Click **Post reel to feed**.
6. Like, save, comment on, or share the new feed post.

Manual upload path:

1. Open or download `public/samples/payment-routing-readiness-aidoc.md`.
2. In Razorwire, click **Upload .txt / .md / .html**.
3. Select the sample file.
4. Click **Create reel draft**.

## Getting started

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Verification

```bash
npm run lint
npm run build
```

## Prototype boundaries

| Capability | Current behavior | Production follow-up |
|---|---|---|
| Feed actions | Local like/save/comment/share state | Persist actions in backend |
| Video upload | Captures clip metadata and learning takeaway | Upload binary video to object storage and transcode |
| AI generation | Deterministic local draft generator | Claude API summarization/script/storyboard generation |
| AIDocs ingestion | Paste text, load sample, or upload text-like files | Pull docs via Aidocs API/CLI with permissions |
| Voice/video | Playable scene reel + browser voice narration | TTS + slide/diagram rendering + MP4 assembly |
| Auth | No auth | Razorpay SSO and content permissions |
| Persistence | In-memory browser state | Backend database + object storage |

## Suggested next increments

1. Add real Claude integration for summary/script/storyboard generation.
2. Use the installed `aidocs` CLI/API to select and ingest authorized AIDocs.
3. Generate voiceover with a TTS provider and captions from the script.
4. Render scenes as slides/diagrams and stitch them into a short MP4.
5. Replace local state with an API and database.
6. Add Razorpay SSO, ownership, review/approval, and content governance.

## Tech stack

- Next.js App Router
- React
- TypeScript
- Tailwind CSS
