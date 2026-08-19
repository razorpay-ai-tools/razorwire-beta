# Storage

Use Postgres for shared app state and object storage for media.

## Database

Set `DATABASE_URL` in `backend/.env`.

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require
```

Supabase and Neon Postgres URLs work as pasted; the backend maps them to the
installed `psycopg` driver. SQLite remains the default for local-only demos.

## Supabase setup

1. Create a Supabase project.
2. Open Project Settings -> Database -> Connection string.
3. Copy the URI connection string. If `db.<project-ref>.supabase.co` does not
   resolve from your machine, use the Session pooler string instead:

```env
DATABASE_URL=postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require
```

The Supabase free direct DB endpoint is IPv6-only; the shared pooler is IPv4.
4. Paste it into `backend/.env` as `DATABASE_URL`.
5. Keep `DEV_AUTH_EMAIL=you@razorpay.com` while testing without Google SSO.
6. Restart the backend; tables are created on startup.
7. Run:

```bash
cd backend
.venv/bin/python scripts/check_shared_storage.py
```

That script creates a post as user 1, likes/comments as user 2, then reads the
post as user 1 and asserts the shared counts are visible.

The API creates these tables on startup:

- `users`
- `posts`
- `likes`
- `saves`
- `comments`
- `jobs`

Correctness lives in the database:

- `users.email` is unique.
- `likes` has `unique(user_id, post_id)`.
- `saves` has `unique(user_id, post_id)`.
- comments, reactions, jobs, and posts use foreign keys.

## Media

Current uploads still land on local disk via `MEDIA_DIR`. That is fine for one
box. For a shared demo, put uploaded clips and generated MP4s in S3 or Supabase
Storage and store only the URL/key in `posts.media_url`.

ponytail: no migration tool yet. Add Alembic after the schema needs history.
