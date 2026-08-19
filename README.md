# Razorwire

> Every tech spec ships with a 60-second explainer.

Paste an aidocs link or a Slack thread → get a 60-second narrated vertical explainer
with the doc's **real architecture diagram** and a **citation on every scene**,
published to an internal short-video feed.

## Team Unrealistic Expectations

Shivang · Sarthak Kapoor · Saksham Garg · Sambhav Jain

Submission: [doc_r523noskel555f7f](https://aidocs.razorpay.com/app/d/doc_r523noskel555f7f)
Design record: [`docs/DESIGN.md`](docs/DESIGN.md) · Plan: [`docs/PLAN.md`](docs/PLAN.md)
· Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md)

Repo: [`razorpay-ai-tools/razorwire-beta`](https://github.com/razorpay-ai-tools/razorwire-beta)

> **This repo is public.** Never commit credentials, customer data, PII, or production
> config. `.env` files are gitignored — keep it that way.
>
> The org enforces SAML SSO, so a token or SSH key must be explicitly authorized for
> `razorpay-ai-tools` before it can push. A global git config here rewrites
> `https://github.com/` to SSH, so the remote deliberately carries a username
> (`https://<you>@github.com/...`) to stay on HTTPS and bypass that rewrite.

---

## Run it

One command starts both servers:

```bash
npm run dev:all
```

It creates missing local env files, installs missing dependencies, then starts:

- web app: `http://localhost:3000`
- backend API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

Requires `node`, `npm`, and `python3`. Python 3.12 is preferred; the local
launcher also works with macOS Python 3.9 by installing the annotation backport
listed in `backend/requirements.txt`.

First run creates:

- `backend/.env`
- `.env.local`

Add secrets only to `backend/.env`, then rerun `npm run dev:all`.

`backend/.env`:

```env
DATABASE_URL=sqlite:///./razorwire.db
WEB_ORIGIN=http://localhost:3000
DEV_AUTH_EMAIL=you@razorpay.com
GOOGLE_CLIENT_ID=
ALLOWED_HD=razorpay.com
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5
MEDIA_DIR=./.storage
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=razorwire-videos
SUPABASE_STORAGE_PUBLIC=true
MAX_UPLOAD_BYTES=52428800
```

`.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

`DEV_AUTH_EMAIL` is the local auth bypass. Unset, the API requires a Google ID
token restricted to the `razorpay.com` hosted domain.

An empty database has an empty feed. Seed sample channels, posts and follows —
idempotent, so re-running it adds nothing:

```bash
cd backend
.venv/bin/python scripts/seed.py
```

For shared state, replace the default SQLite `DATABASE_URL` with a hosted Postgres URL
from Supabase or Neon. See [`docs/STORAGE.md`](docs/STORAGE.md).

For shared video uploads, create the Supabase Storage bucket named in
`SUPABASE_STORAGE_BUCKET` and set `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`.

To prove cross-user consistency after pointing at Supabase:

```bash
cd backend
.venv/bin/python scripts/check_shared_storage.py
```

`scripts/seed.py` is idempotent and does not migrate. On a database that predates
channels, either `rm backend/razorwire.db` or add the two columns in place:

```sql
ALTER TABLE users ADD COLUMN bio VARCHAR NOT NULL DEFAULT '';
ALTER TABLE posts ADD COLUMN channel_id VARCHAR;
```

## Verify

```bash
npm run lint && npx tsc --noEmit && npm run build
node src/components/scenes/__check.mts     # scene dispatcher + mermaid fallback
cd backend && uv run pytest -q             # 123 tests
```

---

## How it works

```
aidocs doc ─┐
            ├─▶ normalise ──▶ script ──▶ storyboard ──▶ feed
slack thread┘   sections +    Claude     contract       browser reel
                scrub         tool call                 + Web Speech
                                             │
                                             └─▶ storyboard.json ──▶ MP4
                                                 on disk            voice → frames
                                                                    → ffmpeg
```

One video, click to playing, and who pays for what:

```
1  browser  → POST /generate {kind, docId|slackUrl}       → job id      ours, free
2  browser  → GET /jobs/{id}, ~1×/sec                     → live states ours, free
3a backend  → aidocs / Slack   fetch + normalise + scrub                internal, free
3b backend  → Claude API       doc text + tool schema                   PAID, cents
   ─────────── storyboard.json written to <WORK_DIR>/<job_id>/ ───────────
4  backend  → Kokoro (local)   narration → wav + measured duration      local, free
5a backend  → Playwright       screenshot /render?post=…&scene=N        local, free
5b backend  → ffmpeg           pngs + wavs + captions → video.mp4       local, free
6  backend  → database         Post row + job published                 ours, free
7  browser  → /feed, /media/…  plays like any web video                 ours, free
```

**Only 3b leaves the perimeter.** Everything else is our box or an internal service.

Steps 4–6 are not built yet — see *Known gaps*.

### The handoff to the renderer is one file

```
<WORK_DIR>/<job_id>/storyboard.json    step 3 output — the render contract
                    scene1.wav ...     step 4, Kokoro
                    scene1.png ...     step 5a, Playwright
                    video.mp4          step 5b, ffmpeg → copied into MEDIA_DIR
```

`WORK_DIR` is deliberately **not** served at a URL. `MEDIA_DIR` is public at `/media`,
and only the finished MP4 belongs there.

### Two contracts, and why

Both are generated from the same pydantic models, so they cannot drift:

```bash
npm run gen:types      # → contracts/*.schema.json, src/lib/storyboard.types.ts
```

| | `backend/app/storyboard.py` | `backend/app/render_contract.py` |
|---|---|---|
| Read by | web app, browser reel | the MP4 renderer |
| Scene shape | flat, `scene.type` | nested, `scene.visual.kind` |
| Extras | `cite`, `broll`, `durationMs` | none — stripped at the boundary |

**Do not mix them.** The feed's scene components dispatch on internal `scene.type`; put
the render shape in `Post.storyboard` and all six scenes fall through to
`UnsupportedScene` with nothing raising anywhere. Tests assert the two reject each other.

### Two sources

Both normalise to the same `Section(heading, text)`, so the prompt, validator and
contract cannot tell them apart.

| | aidocs | Slack |
|---|---|---|
| Fetch | `aidocs docs pull <id>` | `conversations.replies` |
| Cite anchor | section heading | `Author, HH:MM` per message |
| Scrubbed | no (an authored doc) | **yes, in the adapter** |
| Gate | doc id | bot in channel **and** `SLACK_ALLOWED_CHANNELS` |

`backend/app/scrub.py` redacts entity ids, cards, phones, emails, VPAs, IPs, PAN,
Aadhaar and API tokens **before any model call** — in the adapter, never in the prompt.
A prompt instruction not to repeat a card number is advice; removing it first is a
guarantee. Redactions are visible (`[entity id]`) so the sentence still reads.

Rules the contract enforces, worth knowing before touching the pipeline:

1. **The model never sets `durationMs`** — scene length comes from measured narration
   audio in step 4. Desync becomes a validation error rather than a debugging session.
2. **The model never sets `broll.clipId`** — it picks a `mood` from a closed set and a
   resolver maps that to a pre-generated clip. No spec text reaches a video prompt, and
   nothing is generated on the request path.
3. **Every factual scene from a real source needs a `cite`.** `bullets`, `diagram`,
   `compare` and `code` carry claims; `title` and `outro` do not, and must not show a
   chip. An aidoc cites a section heading; a Slack thread cites `Ananya R, 16:30`. Only
   `topic` is exempt, because there is no source to point at.
4. **Diagrams cap at 7 nodes** and must open `graph LR|TB|TD` — past that they are
   illegible in a 9:16 frame, and the renderer rejects a malformed one loudly.
5. **4–6 scenes, narration ≤2 sentences**, no URLs, markdown or emoji. The free TTS
   reads a URL out character by character.

### Why Veo is only the background

Veo 3.x cannot render legible text or an accurate diagram — a known architectural
limitation, not a prompting problem. Footage is therefore a background plate, and every
legible thing on screen is DOM. That is the entire reason the diagram is trustworthy.
See `docs/PLAN.md` §5.5.

Note the MP4 path (steps 4–6) draws its frames by screenshotting our own web app, so
Veo is not on it at all — `broll.mood` now only dresses the browser feed.

### Why there is no MP4 yet

The browser reel plays a storyboard directly and narrates with the Web Speech API, so
generation finishes in seconds with no render queue, no Remotion licence question, and no
voice data leaving the perimeter. MP4 export is the follow-up, not the default.
See `docs/PLAN.md` §5.6. `storyboard.json` is already written to disk for it.

---

## Layout

```
backend/
  app/storyboard.py       THE CONTRACT — validation, tool schema, TS codegen source
  app/render_contract.py  THE HANDOFF — the renderer's schema, projection, write_bundle
  app/aidocs.py           fetch a doc by id, normalise to citable sections
  app/slack.py            fetch a thread, normalise to citable sections, scrubbed
  app/scrub.py            PII and secret redaction at the ingestion boundary
  app/pipeline.py         Claude script stage; validation errors fed back for self-repair
  app/main.py             feed, channels, profiles, posts, reactions, uploads, jobs
  app/models.py           eight DB tables; reaction counts derived, never denormalised
  scripts/seed.py         sample channels, posts and follows for an empty database
  tests/                  123 tests — api, render contract, ingestion
src/
  app/page.tsx         app shell — feed is the default view, create is a sheet over it
  components/feed/     THE FOCUS SCREEN — snap feed, both post variants
  components/scenes/   six 9:16 scene templates + mermaid
  components/create/   generate panel, pipeline stepper, upload form, inspector
  components/ui.tsx    shared primitives; SVG icons that take a required label
  lib/api.ts           typed client + derived view helpers
  lib/storyboard.types.ts   GENERATED — do not edit
```

## Two post kinds

The feed renders both, deliberately distinct — a clip must not look like a generated post
that failed to load.

| | `generated` | `clip` |
|---|---|---|
| Source | a storyboard | an uploaded video |
| Top | one progress segment per scene | scrub position |
| Citations | per scene | none |
| Captions | narration, a sentence at a time | none |
| Actions | like, comment, save, **Spec** | like, comment, save |

## Known gaps

- **Neither source is automatic.** Both are on-demand; no watcher, poller or Events API.
  The push trigger is the actual product — see `docs/PLAN.md` §11.
- **Slack has never spoken to the real API.** `parse_thread` is pure and fully tested from
  fixtures, but there is no bot token yet, so `_call` and `_display_name` are unproven.
  Needs scopes `channels:history`, `groups:history`, `channels:read`, `users:read`, and
  the bot invited to each channel.
- **aidocs runs on a personal login.** `_pull_html` shells out to the CLI, which reads
  `~/.config/aidocs/config.json`. So it only works on that laptop, and docs are read with
  *that user's* permissions rather than the requester's. Fix is `aidocs sa create` plus a
  bearer token over HTTP; the CLI already takes `--server` and `--token`.
- **No consent flow.** Slack contributors are captured and attributed, but nobody is
  notified their words became a post and there is no takedown.
- **No Veo clip library yet.** `brollSrc` only requests a clip once the resolver has
  assigned a `clipId`, so scenes fall back to an accent gradient with no failed request.
- **MP4 export unbuilt**, so the `voicing` and `rendering` job states never fire.
  `_run_job` goes straight to `published`, which is right for the browser reel and wrong
  once step 4 lands. `storyboard.json` is already on disk waiting for it.
- **`/render?post=…&scene=N` does not exist**, and step 5a screenshots it. `src/app/` has
  only `page.tsx`.
- **Uploads go to local disk** through the app. Fine for one box; presign beyond that.
- **No migrations.** Fresh DBs use `create_all`; add Alembic after the schema stabilises.
  On a SQLite file that predates channels, either `rm backend/razorwire.db` or add the
  two columns in place:
  ```sql
  ALTER TABLE users ADD COLUMN bio VARCHAR NOT NULL DEFAULT '';
  ALTER TABLE posts ADD COLUMN channel_id VARCHAR;
  ```
- **`ink-subtle` is 3.7:1** against surface-1, under the floor for body text. It is for
  timestamps, hints and disabled states only — use `ink-muted` for secondary copy.
- **Diagram legibility at 360px**: a 7-node vertical graph letterboxes to roughly 11px
  labels. Check on a real phone before trusting it; the node cap is what keeps it this
  side of readable.
