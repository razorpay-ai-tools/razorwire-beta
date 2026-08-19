# AiSites hosting

AiSites can host Razorwire's built frontend. It does not run the FastAPI backend
process, so keep the backend on a normal app host and point the frontend at it.

## Deploy frontend

```bash
export NEXT_PUBLIC_API_URL=https://YOUR_BACKEND_HOST
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

To run without FastAPI, replace backend calls with AiSites primitives:

- posts/comments/likes/saves/views: `/__flash_db__`
- signed-in user: `/__flash_me__`
- secrets/LLM calls: `/__flash_proxy__`
- live feed refresh: `/__flash_ws__`

That is a backend rewrite, not a hosting switch.
