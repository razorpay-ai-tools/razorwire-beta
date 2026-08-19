# Render backend hosting

Use Render for the public FastAPI backend URL. AiSites still hosts the frontend;
Supabase still stores DB rows and uploaded videos.

## Deploy

1. Push this branch to GitHub.
2. Open Render → New → Blueprint.
3. Select this repo and branch.
4. Render reads `render.yaml` and creates `razorwire-api`.
5. Fill the prompted secrets:

```env
DATABASE_URL=postgresql://postgres:...@db.bkizgcbhtdglxutwhvcl.supabase.co:5432/postgres
SUPABASE_SERVICE_ROLE_KEY=...
ANTHROPIC_API_KEY=...
```

After deploy, the backend URL should be:

```txt
https://razorwire-api.onrender.com
```

Verify:

```bash
curl https://razorwire-api.onrender.com/health
```

Expected:

```json
{"status":"ok"}
```

## Redeploy AiSites frontend with backend enabled

```bash
export NEXT_PUBLIC_BACKEND_MODE=aisites
export NEXT_PUBLIC_API_URL=https://razorwire-api.onrender.com
npm run build:aisites
aisites deploy razorwire ./out --publish
```

Now:

- feed/social/profile/channel state uses AiSites DB
- video upload uses Render FastAPI → Supabase Storage
- generation uses Render FastAPI → Claude/Aidocs/Slack → AiSites-created post

## Demo security note

`DEV_AUTH_EMAIL=aisites@razorpay.com` keeps upload/generation working from the
AiSites SSO frontend without adding a token bridge. This is acceptable for a
hackathon demo. For production, replace it with a real signed request from
AiSites to FastAPI.
