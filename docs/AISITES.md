# AiSites hosting

AiSites can host Razorwire's built frontend. It does not run the FastAPI backend
process, so keep the backend on a normal app host and point the frontend at it.

Razorwire supports two frontend backend modes:

- `api` — existing FastAPI backend. This is the default.
- `aisites` — legacy adapter for AiSites DB experiments. Do not use for the shared
  hosted demo; app data lives in the Railway backend.

## Deploy frontend

```bash
export NEXT_PUBLIC_BACKEND_MODE=api
export NEXT_PUBLIC_API_URL=https://razorwire-api-production.up.railway.app
npm run build:aisites
aisites auth login https://aisites.razorpay.com
aisites deploy razorwire ./out --publish
```

The published frontend will be:

```txt
https://razorwire.aisites.razorpay.com/
```

## Backend config

Set these on the backend host:

```env
WEB_ORIGIN=https://razorwire.aisites.razorpay.com
DATABASE_URL=postgresql://...
SUPABASE_URL=https://bkizgcbhtdglxutwhvcl.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_STORAGE_BUCKET=razorwire-videos
SUPABASE_STORAGE_PUBLIC=true
```

## Current hosted data path

- AiSites serves the static frontend and provides the signed-in viewer via
  `/__flash_me__`.
- The frontend sends that viewer email to Railway as `X-Dev-Email`.
- Railway handles feed, posts, likes, saves, comments, profiles, channels,
  uploads, and generation.
- Supabase Postgres stores app data; Supabase Storage stores video bytes.

## Test the adapter

```bash
npm run check:aisites
```

This only covers the legacy AiSites DB adapter.
