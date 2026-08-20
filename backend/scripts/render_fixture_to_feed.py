"""Render the bundled storyboard fixture straight into the feed as an MP4 post.

Lets you exercise the render pipeline end to end WITHOUT an ANTHROPIC_API_KEY: the
render half (voice -> frames -> mp4 -> publish) needs no LLM; only the scripting
stage does. Run from the backend/ directory so media paths match the server:

    PYTHONPATH=. .venv/bin/python scripts/render_fixture_to_feed.py

Then refresh http://localhost:3000 — the new "AI reel" post plays the MP4.
"""

from __future__ import annotations

import json
import pathlib

from sqlmodel import Session, select

from app.config import settings
from app.models import Post, User, _engine, init_db, utcnow
from app.pipeline import storyboard_to_json
from app.render import render_video
from app.render.publish import store_mp4
from app.storyboard import validate_storyboard

FIXTURE = pathlib.Path(__file__).resolve().parents[2] / "src/lib/fixtures/otm-rearch.storyboard.json"


def main() -> None:
    init_db()
    sb = validate_storyboard(json.loads(FIXTURE.read_text()), stage="script")
    print(f"rendering {len(sb.scenes)} scenes: {[s.type for s in sb.scenes]}")

    work = pathlib.Path(settings.work_dir) / "fixture-demo"
    result = render_video(sb, work)
    print(f"rendered {result.mp4_path} ({result.duration_ms} ms, {result.mp4_path.stat().st_size} bytes)")

    with Session(_engine) as session:
        email = settings.dev_auth_email or "demo@razorpay.com"
        user = session.exec(select(User).where(User.email == email)).first()
        if user is None:
            user = User(email=email, name=email.split("@")[0].replace(".", " ").title())
            session.add(user)
            session.commit()
            session.refresh(user)

        media_url, storage_key = store_mp4(result.mp4_path, f"fixture_{utcnow().strftime('%Y%m%d%H%M%S')}")
        post = Post(
            author_id=user.id,
            title=sb.meta.title,
            tags=list(sb.meta.tags),
            kind="generated",
            media_url=media_url,
            storage_key=storage_key,
            duration_ms=result.duration_ms,
            storyboard=storyboard_to_json(sb),
            source_doc_id=sb.source.doc_id,
        )
        session.add(post)
        session.commit()
        session.refresh(post)
        print(f"\npublished post {post.id} by {user.email}")
        print("refresh http://localhost:3000 — it is the newest post in the feed")


if __name__ == "__main__":
    main()
