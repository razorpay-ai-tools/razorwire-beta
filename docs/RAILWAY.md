# Railway backend hosting

Railway can deploy the FastAPI backend from the local `backend/` directory, so it
does not need GitHub repo access.

## Deployed backend

```txt
https://razorwire-api-production.up.railway.app
```

Health:

```bash
curl https://razorwire-api-production.up.railway.app/health
```

Expected:

```json
{"status":"ok"}
```

## Keep warm

Use any external uptime monitor to ping `/health` every 3-5 minutes:

```txt
https://razorwire-api-production.up.railway.app/health
```

Treat this as demo warmup, not an always-on production guarantee. Free providers
may still cold-start or rate-limit idle services.

## Required Railway env vars

Set on the `razorwire-api` service:

```env
PYTHON_VERSION=3.12.7
WEB_ORIGIN=https://razorwire.aisites.razorpay.com
PUBLIC_BASE_URL=https://razorwire-api-production.up.railway.app
DEV_AUTH_EMAIL=aisites@razorpay.com
DATABASE_URL=...
SUPABASE_URL=https://bkizgcbhtdglxutwhvcl.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_STORAGE_BUCKET=razorwire-videos
SUPABASE_STORAGE_PUBLIC=true
MAX_UPLOAD_BYTES=52428800
ANTHROPIC_MODEL=claude-sonnet-5
ANTHROPIC_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
GEMINI_API_KEY=...
```

AI generation uses Anthropic first when `ANTHROPIC_API_KEY` is set, then Gemini
when `GEMINI_API_KEY` is set. Video upload only needs the Supabase values.

## Redeploy backend from local checkout

```bash
cd backend
railway up --detach
```

`backend/railway.json` pins the FastAPI start command and healthcheck.

## Redeploy AiSites frontend against Railway

```bash
export NEXT_PUBLIC_BACKEND_MODE=api
export NEXT_PUBLIC_API_URL=https://razorwire-api-production.up.railway.app
npm run build:aisites
aisites deploy razorwire ./out --publish
```

Current AiSites URL:

```txt
https://razorwire.aisites.razorpay.com/
```
