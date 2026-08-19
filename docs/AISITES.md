# AiSites hosting

AiSites can host Razorwire's built frontend. It does not run the FastAPI backend
process, so keep the backend on a normal app host and point the frontend at it.

Razorwire supports two frontend backend modes:

- `api` — existing FastAPI backend. This is the default.
- `aisites` — AiSites DB for feed/profile/channels/social state. Video upload and
  generation still call FastAPI through `NEXT_PUBLIC_API_URL` when configured.

## Deploy frontend

```bash
export NEXT_PUBLIC_BACKEND_MODE=aisites
export NEXT_PUBLIC_API_URL=https://razorwire-api.onrender.com
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

## AiSites-only backend path

The `aisites` adapter already uses:

- posts/comments/likes/saves/views: `/__flash_db__`
- signed-in user: `/__flash_me__`

Still external/backend-backed:

- video uploads
- aidocs/Slack ingestion
- Claude generation/jobs

Those need either FastAPI or a later `/__flash_proxy__` rewrite.

## Test the adapter

```bash
npm run check:aisites
```

This uses mocked dummy users and asserts that feed, profile, channels, follows,
likes, saves, comments, views and deletes only call `/__flash_*` endpoints.
