"""Sample feed: channels, posts in each, and a follow for every existing user.

Run it against an empty database so the feed, the channel views and the following
feed all have something in them before a demo:

    cd backend && uv run python scripts/seed.py

Idempotent -- channels are keyed on slug and posts on title, so a second run adds
nothing. It does NOT migrate: after a schema change, `rm razorwire.db` first.

ponytail: every generated post reuses the one committed storyboard fixture with its
title swapped. Sample data does not need six distinct scripts; run the real pipeline
when you want real scenes.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import Channel, Follow, Post, User, _engine, init_db, utcnow  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[2] / "src/lib/fixtures/otm-rearch.storyboard.json"
SAMPLE_CLIP = "sample-culture-clip.mp4"

# Order matters only for display. Announcements is first because it is the one channel
# the system posts to on its own: a Slack announcement turned into a video lands here,
# which is why GeneratePanel defaults to it for a Slack source.
CHANNELS = [
    ("Announcements", "Ships, launches and changes -- straight from the thread that announced them."),
    ("Architecture", "How the systems are put together, and why."),
    ("Payments Core", "Mandates, refunds, routing -- the money path."),
    ("Culture", "How we work: rituals, crits, retros."),
    ("Incident Reviews", "What broke, what we changed."),
]

#: Slug of the channel above that generated announcements go to. Derived the same way
#: the loop derives every slug, so renaming the channel cannot leave this stale.
ANNOUNCEMENTS_SLUG = CHANNELS[0][0].lower().replace(" ", "-")

AUTHORS = [
    ("asha.iyer@razorpay.com", "Asha Iyer", "Payments platform. Explains mandates to anyone who asks."),
    ("dev.kumar@razorpay.com", "Dev Kumar", "Infra. Collects post-mortems."),
]

# (channel slug, author index, title, kind)
POSTS = [
    ("architecture", 0, "UPI One-Time Mandates, rearchitected", "generated"),
    ("architecture", 1, "Why pg-router owns the rearch decision", "generated"),
    ("payments-core", 0, "Where block_fund is actually set", "generated"),
    ("payments-core", 1, "SBMD debits against a blocked balance", "generated"),
    ("culture", 1, "How we run design crit", "clip"),
    ("incident-reviews", 0, "The stale splitz cache outage, in 60 seconds", "generated"),
]


def storyboard_titled(title: str) -> dict:
    board = copy.deepcopy(json.loads(FIXTURE.read_text()))
    board["meta"]["title"] = title
    return board


def main() -> None:
    init_db()
    clip_available = (Path(settings.media_dir) / SAMPLE_CLIP).exists()
    if not clip_available:
        print(f"! {SAMPLE_CLIP} is not in {settings.media_dir} -- skipping clip posts")

    with Session(_engine) as session:
        authors = []
        for email, name, bio in AUTHORS:
            user = session.exec(select(User).where(User.email == email)).first()
            if user is None:
                user = User(email=email, name=name, bio=bio)
                session.add(user)
                session.commit()
                session.refresh(user)
            authors.append(user)

        # The local dev identity is created lazily on its first request, which is after
        # this runs -- so it would end up following nothing. Create it here.
        if settings.dev_auth_enabled:
            email = settings.dev_auth_email
            if session.exec(select(User).where(User.email == email)).first() is None:
                session.add(User(email=email, name=email.partition("@")[0]))
                session.commit()

        channels: dict[str, Channel] = {}
        for name, description in CHANNELS:
            slug = name.lower().replace(" ", "-")
            channel = session.exec(select(Channel).where(Channel.slug == slug)).first()
            if channel is None:
                channel = Channel(
                    slug=slug, name=name, description=description, created_by=authors[0].id
                )
                session.add(channel)
                session.commit()
                session.refresh(channel)
            channels[slug] = channel

        # Every user follows every sample channel, so the following feed is not empty
        # the first time someone taps it.
        for user in session.exec(select(User)).all():
            for channel in channels.values():
                already = session.exec(
                    select(Follow).where(
                        Follow.user_id == user.id, Follow.channel_id == channel.id
                    )
                ).first()
                if already is None:
                    session.add(Follow(user_id=user.id, channel_id=channel.id))
        session.commit()

        created = 0
        now = utcnow()
        for index, (slug, author_index, title, kind) in enumerate(POSTS):
            if kind == "clip" and not clip_available:
                continue
            # Keyed on title AND channel: a hand-made post that happens to share a
            # title should not leave a sample channel empty.
            already = session.exec(
                select(Post).where(Post.title == title, Post.channel_id == channels[slug].id)
            ).first()
            if already:
                continue

            session.add(
                Post(
                    author_id=authors[author_index].id,
                    channel_id=channels[slug].id,
                    title=title,
                    category=channels[slug].name,
                    team="payments-platform" if author_index == 0 else "infra",
                    tags=["sample"],
                    kind=kind,
                    storyboard=storyboard_titled(title) if kind == "generated" else None,
                    source_doc_id="doc_sample_otm_rearch" if kind == "generated" else None,
                    media_url=f"/media/{SAMPLE_CLIP}" if kind == "clip" else None,
                    views=40 + index * 17,
                    # spread the timestamps so keyset pagination has a real ordering
                    created_at=now - timedelta(hours=index * 5),
                )
            )
            created += 1
        session.commit()

    print(f"seeded {len(channels)} channels, {created} posts")


if __name__ == "__main__":
    main()
