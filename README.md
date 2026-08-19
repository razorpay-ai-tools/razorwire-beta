# Razorwire

> Every tech spec ships with a 60-second explainer.

Paste an aidocs link → get a 60-second narrated vertical explainer with the doc's **real
architecture diagram** and a **citation on every scene**, published to an internal
short-video feed.

Team **Unrealistic Expectations** — Shivang · Sarthak · Saksham · Sambhav
Submission: [doc_r523noskel555f7f](https://aidocs.razorpay.com/app/d/doc_r523noskel555f7f)
Design record: [`docs/DESIGN.md`](docs/DESIGN.md) · Plan: [`docs/PLAN.md`](docs/PLAN.md)

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

Config files:

- copy `backend/.env.example` to `backend/.env`
- copy `.env.example` to `.env.local`

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
```

`.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

`DEV_AUTH_EMAIL` is the local auth bypass. Unset, the API requires a Google ID
token restricted to the `razorpay.com` hosted domain.

For shared state, replace the default SQLite `DATABASE_URL` with a hosted Postgres URL
from Supabase or Neon. See [`docs/STORAGE.md`](docs/STORAGE.md).

To prove cross-user consistency after pointing at Supabase:

```bash
cd backend
.venv/bin/python scripts/check_shared_storage.py
```

## Verify

```bash
npm run lint && npx tsc --noEmit && npm run build
node src/components/scenes/__check.mts     # scene dispatcher + mermaid fallback
cd backend && uv run pytest -q             # 35 tests
```

---

## How it works

```
aidocs doc ──▶ normalise ──▶ script ──▶ storyboard ──▶ feed
  CLI pull     sections      Claude     contract       browser reel
                             tool call                 + Web Speech
```

**The contract is the spine.** `backend/app/storyboard.py` is the single source of truth
and drives three consumers: runtime validation, the Claude tool `input_schema`, and the
web app's TypeScript types. Regenerate the derived artifacts with:

```bash
npm run gen:types      # → contracts/*.schema.json, src/lib/storyboard.types.ts
```

Four rules it enforces, worth knowing before touching the pipeline:

1. **The model never sets `durationMs`** — scene length comes from measured narration
   audio. Desync becomes a validation error rather than a debugging session.
2. **The model never sets `broll.clipId`** — it picks a `mood` from a closed set and a
   resolver maps that to a pre-generated Veo clip. No spec text reaches a video prompt,
   and nothing is generated on the request path.
3. **Every factual scene from a doc needs a `cite`.** `bullets`, `diagram`, `compare` and
   `code` carry claims; `title` and `outro` do not, and must not show a chip.
4. **Diagrams cap at 7 nodes** — past that they are illegible in a 9:16 frame.

### Why Veo is only the background

Veo 3.x cannot render legible text or an accurate diagram — a known architectural
limitation, not a prompting problem. Footage is therefore a background plate, and every
legible thing on screen is DOM. That is the entire reason the diagram is trustworthy.
See `docs/PLAN.md` §5.5.

### Why there is no MP4 yet

The browser reel plays a storyboard directly and narrates with the Web Speech API, so
generation finishes in seconds with no render queue, no Remotion licence question, and no
voice data leaving the perimeter. MP4 export is the follow-up, not the default.
See `docs/PLAN.md` §5.6.

---

## Layout

```
backend/
  app/storyboard.py    THE CONTRACT — validation, tool schema, TS codegen source
  app/aidocs.py        fetch a doc by id, normalise to citable sections
  app/pipeline.py      Claude script stage; validation errors fed back for self-repair
  app/main.py          feed, posts, likes, saves, comments, views, uploads, jobs
  app/models.py        six DB tables; reaction counts derived, never denormalised
  tests/test_api.py    35 tests
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

- **No Veo clip library yet.** `brollSrc` points at `/broll/<mood>.mp4`; missing files
  fall back to an accent gradient — the designed path, but it does log 404s.
- **MP4 export unbuilt**, so the `voicing` and `rendering` job states never fire.
- **Uploads go to local disk** through the app. Fine for one box; presign beyond that.
- **No migrations.** Fresh DBs use `create_all`; add Alembic after the schema stabilises.
- **Diagram legibility at 360px**: a 7-node vertical graph letterboxes to roughly 11px
  labels. Check on a real phone before trusting it; the node cap is what keeps it this
  side of readable.
