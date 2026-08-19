# Razorwire

> Every tech spec ships with a 60-second explainer.

Paste an aidocs link or a Slack thread → get a 60-second narrated vertical explainer
with the doc's **real architecture diagram** and a **citation on every scene**,
published to an internal short-video feed.

Built by **Team Unrealistic Expectations** for the Razorpay hackathon.

| | |
|---|---|
| **Shivang** | ingestion, pipeline |
| **Sarthak** | renderer — voice, screenshots, MP4 |
| **Saksham** | contract, ingestion, API |
| **Sambhav** | feed, upload, web app |

Submission: [doc_r523noskel555f7f](https://aidocs.razorpay.com/app/d/doc_r523noskel555f7f)
· Plan: [`docs/PLAN.md`](docs/PLAN.md) · Design: [`docs/DESIGN.md`](docs/DESIGN.md)
· Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md)

Repo: [`razorpay-ai-tools/razorwire-beta`](https://github.com/razorpay-ai-tools/razorwire-beta)

> **This repo is public.** Never commit credentials, customer data, PII, or production
> config. `.env` files are gitignored — keep it that way.
>
> The org enforces SAML SSO, so a token or SSH key must be explicitly authorized for
> `razorpay-ai-tools` before it can push (`gh` and `git` both fail with a SAML notice
> until you do). See [`CONTRIBUTING.md`](CONTRIBUTING.md#access).

---

## Run it

Two processes. Node serves the web app, Python serves the API.

```bash
# 1. backend  (http://localhost:8000, OpenAPI at /docs)
cd backend
cp ../.env.example .env                      # then fill ANTHROPIC_API_KEY
echo 'DEV_AUTH_EMAIL=you@razorpay.com' >> .env
uv sync
uv run uvicorn app.main:app --reload --port 8000

# 2. web app  (http://localhost:3000)
npm install
npm run dev
```

`DEV_AUTH_EMAIL` is the local auth bypass. Unset, the API requires a Google ID token
restricted to the `razorpay.com` hosted domain.

## Verify

```bash
npm run lint && npx tsc --noEmit && npm run build
node src/components/scenes/__check.mts     # scene dispatcher + mermaid fallback
cd backend && uv run pytest -q             # 112 tests
```

---

## One video, click to playing

```
1  browser  → POST /generate {kind, docId|slackUrl}       → job id      ours, free
2  browser  → GET /jobs/{id}, ~1×/sec                     → live states ours, free
3a backend  → aidocs / Slack        fetch + normalise + scrub           internal, free
3b backend  → Claude API            doc text + tool schema              PAID, cents
   ─────────── storyboard.json written to disk ───────────
4  backend  → Kokoro (local)        narration → wav + measured duration local, free
5a backend  → Playwright (local)    screenshot /render?post=…&scene=N   local, free
5b backend  → ffmpeg (local)        pngs + wavs + captions → video.mp4  local, free
6  backend  → SQLite                Post row + job published            ours, free
7  browser  → GET /feed, /media/…   plays like any web video            ours, free
```

Only **3b** leaves the perimeter. Everything else is our box or an internal service.

### The handoff is one file

```
<work_dir>/<job_id>/storyboard.json    step 3 output — the contract
                    scene1.wav ...     step 4, Kokoro
                    scene1.png ...     step 5a, Playwright
                    video.mp4          step 5b, ffmpeg → copied into media_dir
```

`work_dir` is **not** served at a URL. `media_dir` is public at `/media`, and only the
finished MP4 belongs there.

---

## Two contracts, and why

The backend owns both because it owns the pipeline. They are generated from the same
pydantic models, so they cannot drift:

```bash
npm run gen:types    # → contracts/*.schema.json, src/lib/storyboard.types.ts
```

| | `backend/app/storyboard.py` | `backend/app/render_contract.py` |
|---|---|---|
| Who reads it | web app, browser reel | the MP4 renderer |
| Scene shape | flat, `scene.type` | nested, `scene.visual.kind` |
| Extras | `cite`, `broll`, `durationMs` | none — stripped at the boundary |

**Do not mix them.** The feed's scene components dispatch on internal `scene.type`;
put the render shape in `Post.storyboard` and all six scenes fall through to
`UnsupportedScene` with nothing raising anywhere. Tests assert the two reject each
other.

### Rules the contract enforces

1. **The model never sets `durationMs`** — scene length comes from measured narration
   audio in step 4. Desync becomes a validation error, not a debugging session.
2. **Every factual scene from a real source needs a `cite`.** `bullets`, `diagram`,
   `comparison` and `code` carry claims; `title` and `outro` do not, and must not show
   a chip. An aidoc cites a section heading; a Slack thread cites `Ananya R, 16:30`.
3. **Diagrams cap at 7 nodes** and must start `graph LR|TB|TD` — past that they are
   illegible in a 9:16 frame, and the renderer rejects a malformed one loudly.
4. **4–6 scenes, narration ≤2 sentences**, no URLs, markdown or emoji — the free TTS
   reads a URL out character by character.

---

## Two sources

Both normalise to the same `Section(heading, text)`, so the prompt, validator and
contract cannot tell them apart.

| | aidocs | Slack |
|---|---|---|
| Fetch | `aidocs docs pull <id>` | `conversations.replies` |
| Cite anchor | section heading | `Author, HH:MM` per message |
| Scrubbed | no (authored doc) | **yes, in the adapter** |
| Gate | doc id | bot in channel **and** `SLACK_ALLOWED_CHANNELS` |

`backend/app/scrub.py` redacts entity ids, cards, phones, emails, VPAs, IPs, PAN,
Aadhaar and API tokens **before any model call** — in the adapter, never in the prompt.
A prompt instruction not to repeat a card number is advice; removing it first is a
guarantee. Redactions are visible (`[entity id]`) so the sentence still reads.

---

## Layout

```
backend/
  app/storyboard.py      internal contract — validation, tool schema, TS codegen source
  app/render_contract.py THE HANDOFF — the renderer's schema, projection, write_bundle
  app/aidocs.py          fetch a doc by id, normalise to citable sections
  app/slack.py           fetch a thread, normalise to citable sections, scrubbed
  app/scrub.py           PII and secret redaction at the ingestion boundary
  app/pipeline.py        Claude script stage; validation errors fed back for self-repair
  app/main.py            feed, posts, likes, saves, comments, views, uploads, jobs
  app/models.py          six SQLite tables; reaction counts derived, never denormalised
src/
  app/page.tsx           app shell — feed is the default view, create is a sheet over it
  components/feed/       THE FOCUS SCREEN — snap feed, both post variants
  components/scenes/     six 9:16 scene templates + mermaid
  components/create/     generate panel, pipeline stepper, upload form, inspector
  lib/storyboard.types.ts  GENERATED — do not edit
```

## Two post kinds

The feed renders both, deliberately distinct — a clip must not look like a generated
post that failed to load.

| | `generated` | `clip` |
|---|---|---|
| Source | a storyboard | an uploaded video |
| Top | one progress segment per scene | scrub position |
| Citations | per scene | none |
| Captions | narration, a sentence at a time | none |
| Actions | like, comment, save, **Spec** | like, comment, save |

## Known gaps

- **Neither source is automatic.** Both are on-demand; no watcher, poller or Events
  API. The push trigger is the actual product — see `docs/PLAN.md` §11.
- **Slack has never spoken to the real API.** `parse_thread` is pure and fully tested
  from fixtures, but there is no bot token yet, so `_call` and `_display_name` are
  unproven. Needs scopes `channels:history`, `groups:history`, `channels:read`,
  `users:read`, and the bot invited to each channel.
- **aidocs runs on a personal login.** `_pull_html` shells out to the CLI, which reads
  `~/.config/aidocs/config.json`. So it only works on that laptop, and docs are read
  with *that user's* permissions rather than the requester's. Fix is `aidocs sa create`
  plus a bearer token over HTTP; the CLI already takes `--server` and `--token`.
- **No consent flow.** Slack contributors are captured and attributed, but nobody is
  notified their words became a post and there is no takedown.
- **`voicing` and `rendering` never fire** — `_run_job` goes straight to `published`,
  which is right for the browser reel and wrong once step 4 lands.
- **Uploads go to local disk** through the app. Fine for one box; presign beyond that.
- **No migrations.** `rm backend/razorwire.db` is the reset.
