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
```

`ANTHROPIC_API_KEY` is only needed for AI generation. Video upload only needs the
Supabase values.

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

## aidocs ingestion (required)

Without these, every document fetch fails and `GET /health` reports
`aidocs.ready = "no"`. The container has no `aidocs` CLI and no Google session to
inherit, so a service-account token is the only path.

```
AIDOCS_SERVER = https://aidocs.razorpay.com
AIDOCS_TOKEN  = <service-account key>
```

Mint one:

```bash
aidocs sa create razorwire-ingest          # once; gives sa_...
aidocs sa key create <sa_id> --name railway
```

The secret is shown once. Keys are independent, so revoke one without breaking the
others: `aidocs sa key list <sa_id>` then `aidocs sa key revoke <sa_id> <key_id>`.

Never commit the token. This repo is public, and the key reads any document shared
with the org.

### Check it from outside

```bash
curl -s https://<service>.up.railway.app/health | jq .aidocs
```

| `ready` | Meaning |
|---|---|
| `yes` | service-account token present |
| `probably` | no token, falling back to the CLI — will not work in a container |
| `no` | no token and no CLI; every fetch will fail |
