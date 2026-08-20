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
LITELLM_API_KEY=...
LLM_BASE_URL=https://llm-gateway.razorpay.com
LLM_MODEL=glm-5p2
```

`LITELLM_API_KEY` is only needed for AI generation. Video upload only needs the
Supabase values. A direct `ANTHROPIC_API_KEY` still works as a fallback — clear
`LLM_BASE_URL` if you use one.

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
