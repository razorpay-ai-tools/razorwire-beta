"""Razorwire API.

The surface the web app talks to: an Instagram-shaped feed (posts, likes, saves,
comments, views) plus the storyboard generation pipeline.

Run it:  uv run uvicorn app.main:app --reload --port 8000
Docs at: http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import func
from sqlmodel import Session, col, delete, select

from .aidocs import AidocsUnavailable, fetch_doc
from .auth import current_user
from .config import settings
from .models import (
    Channel,
    Comment,
    Follow,
    Job,
    Like,
    Post,
    Save,
    User,
    get_session,
    init_db,
    utcnow,
)
from .pipeline import run_plan_stage, run_reduce_stage, run_script_stage, storyboard_to_json
from .render_contract import RenderContractInvalid, emit, write_bundle
from .slack import SlackUnavailable, fetch_thread, parse_permalink
from .storage import store_upload
from .storyboard import Storyboard, StoryboardInvalid

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Razorwire API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MEDIA_DIR = Path(settings.media_dir)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


# --------------------------------------------------------------------------- wire types


class _Out(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class UserOut(_Out):
    id: str
    email: str
    name: str
    picture: str | None = None
    bio: str = ""


class ProfileUpdate(_Out):
    """Everything a person may change about themselves. Email comes from the token."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    bio: str | None = Field(default=None, max_length=280)


class ChannelRef(_Out):
    """Just enough channel to render and link a post."""

    id: str
    slug: str
    name: str


class ChannelOut(ChannelRef):
    description: str
    posts: int = 0
    followers: int = 0
    following: bool = False


class ChannelCreate(_Out):
    name: str = Field(min_length=2, max_length=60)
    description: str = Field(default="", max_length=280)


class ProfileOut(_Out):
    user: UserOut
    posts: int
    #: channels this person follows
    channels: list[ChannelOut]


class PostCreate(_Out):
    title: str = Field(min_length=3, max_length=120)
    description: str = ""
    team: str = ""
    category: str = "Product"
    tags: list[str] = Field(default_factory=list)
    accent: str = ""
    kind: Literal["clip", "generated"] = "clip"
    media_url: str | None = None
    storage_key: str | None = None
    thumbnail_url: str | None = None
    duration_ms: int | None = None
    storyboard: dict[str, Any] | None = None
    source_doc_id: str | None = None
    channel_id: str | None = None


class CommentOut(_Out):
    id: str
    text: str
    author: UserOut
    created_at: datetime


class PostOut(_Out):
    id: str
    title: str
    description: str
    team: str
    category: str
    tags: list[str]
    accent: str
    kind: str
    media_url: str | None
    storage_key: str | None
    thumbnail_url: str | None
    duration_ms: int | None
    storyboard: dict[str, Any] | None
    source_doc_id: str | None
    views: int
    created_at: datetime
    author: UserOut
    channel: ChannelRef | None = None

    likes: int = 0
    saves: int = 0
    comments: int = 0
    liked: bool = False
    saved: bool = False


class FeedPage(_Out):
    items: list[PostOut]
    next_cursor: str | None = None


class ToggleOut(_Out):
    active: bool
    count: int


class CommentCreate(_Out):
    text: str = Field(min_length=1, max_length=1000)


class GenerateRequest(_Out):
    kind: Literal["aidoc", "slack", "topic"] = "topic"
    #: The topic, or pasted document text. Optional for kind="aidoc", where the
    #: backend fetches the document itself and only falls back to this if that fails.
    input: str = ""
    doc_id: str | None = None
    doc_title: str | None = None
    doc_url: str | None = None
    #: Slack message permalink, for kind="slack". A link to any reply works — the
    #: adapter resolves it to the parent thread.
    slack_url: str | None = None
    #: What to produce. "reel" plays the storyboard in the browser and narrates with the
    #: Web Speech API — seconds to publish, no tooling. "video" renders an MP4 with a
    #: spoken track, which needs ffmpeg and Chromium on the box and is written as a short
    #: film rather than as slides. Default stays "reel" so nothing changes for callers
    #: that predate the choice.
    format: Literal["reel", "video"] = "reel"
    #: Channel the finished post(s) land in, when the author picked one. Chosen up front
    #: rather than applied by the caller afterwards, because the pipeline is what creates
    #: the posts — and a multi-part job creates several, only one of which the caller
    #: ever learns the id of.
    channel_id: str | None = None


class JobOut(_Out):
    id: str
    state: str
    progress: int
    error: str | None
    #: what was asked for, "reel" or "video" — so a job that published the wrong thing
    #: can be told apart from one that was never asked for the right thing
    format: str
    storyboard: dict[str, Any] | None
    post_id: str | None
    created_at: datetime
    updated_at: datetime


class UploadOut(_Out):
    media_url: str
    storage_key: str


SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


# --------------------------------------------------------------------------- helpers


def _counts(session: Session, post_ids: list[str]) -> dict[str, dict[str, int]]:
    """Batched reaction counts. One grouped query per counter, so no N+1 across the feed."""
    out = {pid: {"likes": 0, "saves": 0, "comments": 0} for pid in post_ids}
    if not post_ids:
        return out
    for key, model in (("likes", Like), ("saves", Save), ("comments", Comment)):
        rows = session.exec(
            select(model.post_id, func.count())
            .where(col(model.post_id).in_(post_ids))
            .group_by(model.post_id)
        ).all()
        for post_id, total in rows:
            out[post_id][key] = total
    return out


def _viewer_flags(session: Session, user: User, post_ids: list[str]) -> tuple[set[str], set[str]]:
    if not post_ids:
        return set(), set()
    liked = set(
        session.exec(
            select(Like.post_id).where(Like.user_id == user.id, col(Like.post_id).in_(post_ids))
        ).all()
    )
    saved = set(
        session.exec(
            select(Save.post_id).where(Save.user_id == user.id, col(Save.post_id).in_(post_ids))
        ).all()
    )
    return liked, saved


def _absolute_media(url: str | None) -> str | None:
    """Media is served by this service, so relative paths must be qualified.

    A bare "/media/x.mp4" resolves against whatever origin the client is on -- for the
    web app that is :3000, where nothing is mounted, so every clip 404'd.
    """
    if not url or not url.startswith("/"):
        return url
    return f"{settings.public_base_url.rstrip('/')}{url}"


def _absolute_storyboard(sb: dict[str, Any] | None) -> dict[str, Any] | None:
    """Scene narration audio lives under /media like the MP4s, so it needs the same
    qualifying as ``media_url`` on the way out. Stored relative, rewritten on read."""
    if not sb or not any(s.get("audioUrl") for s in sb.get("scenes", [])):
        return sb
    return {
        **sb,
        "scenes": [
            {**s, "audioUrl": _absolute_media(s["audioUrl"])} if s.get("audioUrl") else s
            for s in sb["scenes"]
        ],
    }


def _to_out(
    post: Post,
    author: User,
    counts: dict[str, int],
    liked: bool,
    saved: bool,
    channel: Channel | None,
) -> PostOut:
    return PostOut(
        **{
            **post.model_dump(),
            "media_url": _absolute_media(post.media_url),
            "storyboard": _absolute_storyboard(post.storyboard),
        },
        author=UserOut.model_validate(author),
        channel=ChannelRef.model_validate(channel) if channel else None,
        likes=counts["likes"],
        saves=counts["saves"],
        comments=counts["comments"],
        liked=liked,
        saved=saved,
    )


def _hydrate(session: Session, user: User, posts: list[Post]) -> list[PostOut]:
    ids = [p.id for p in posts]
    counts = _counts(session, ids)
    liked, saved = _viewer_flags(session, user, ids)
    authors = {
        u.id: u
        for u in session.exec(select(User).where(col(User.id).in_([p.author_id for p in posts]))).all()
    } if posts else {}
    channel_ids = [p.channel_id for p in posts if p.channel_id]
    channels = {
        c.id: c
        for c in session.exec(select(Channel).where(col(Channel.id).in_(channel_ids))).all()
    } if channel_ids else {}
    return [
        _to_out(
            p,
            authors[p.author_id],
            counts[p.id],
            p.id in liked,
            p.id in saved,
            channels.get(p.channel_id) if p.channel_id else None,
        )
        for p in posts
    ]


def _get_post(session: Session, post_id: str) -> Post:
    post = session.get(Post, post_id)
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "post not found")
    return post


def _toggle(session: Session, model: type[Like] | type[Save], user: User, post_id: str) -> ToggleOut:
    existing = session.exec(
        select(model).where(model.user_id == user.id, model.post_id == post_id)
    ).first()
    if existing is None:
        session.add(model(user_id=user.id, post_id=post_id))
        active = True
    else:
        session.delete(existing)
        active = False
    session.commit()
    count = session.exec(select(func.count()).select_from(model).where(model.post_id == post_id)).one()
    return ToggleOut(active=active, count=count)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _get_channel(session: Session, slug: str) -> Channel:
    channel = session.exec(select(Channel).where(Channel.slug == slug)).first()
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    return channel


def _channels_out(session: Session, user: User, channels: list[Channel]) -> list[ChannelOut]:
    """Batched, like the feed's counters -- a channel list is a feed of channels."""
    ids = [c.id for c in channels]
    if not ids:
        return []

    posts = dict(
        session.exec(
            select(Post.channel_id, func.count())
            .where(col(Post.channel_id).in_(ids))
            .group_by(col(Post.channel_id))
        ).all()
    )
    followers = dict(
        session.exec(
            select(Follow.channel_id, func.count())
            .where(col(Follow.channel_id).in_(ids))
            .group_by(col(Follow.channel_id))
        ).all()
    )
    followed = set(
        session.exec(
            select(Follow.channel_id).where(
                Follow.user_id == user.id, col(Follow.channel_id).in_(ids)
            )
        ).all()
    )
    return [
        ChannelOut(
            **c.model_dump(),
            posts=posts.get(c.id, 0),
            followers=followers.get(c.id, 0),
            following=c.id in followed,
        )
        for c in channels
    ]


# --------------------------------------------------------------------------- routes


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness, plus whether this box can render an MP4.

    The web app reads `render` to decide whether to offer the video option at all. Asking
    here is much kinder than accepting the job and failing it a minute later, and the
    answer is a property of the machine rather than of the request.
    """
    import importlib.util
    import shutil

    ffmpeg = shutil.which("ffmpeg") is not None
    playwright = importlib.util.find_spec("playwright") is not None
    return {
        "status": "ok",
        "render": ffmpeg and playwright,
        "renderMissing": [
            name
            for name, present in (("ffmpeg", ffmpeg), ("playwright", playwright))
            if not present
        ],
    }


@app.get("/me", response_model=UserOut)
def me(user: UserDep) -> User:
    return user


@app.patch("/me", response_model=UserOut)
def update_me(body: ProfileUpdate, session: SessionDep, user: UserDep) -> User:
    """Name and bio only. Absent fields are left alone, so this is a patch not a put."""
    if body.name is not None:
        user.name = body.name.strip()
    if body.bio is not None:
        user.bio = body.bio.strip()
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@app.get("/users/{user_id}", response_model=ProfileOut)
def profile(user_id: str, session: SessionDep, user: UserDep) -> ProfileOut:
    """A profile: who they are, how much they have posted, what they follow.

    Their posts are not inlined -- `GET /feed?author=<id>` returns them with the
    same shape and pagination the feed already has.
    """
    subject = session.get(User, user_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    posts = session.exec(
        select(func.count()).select_from(Post).where(Post.author_id == subject.id)
    ).one()
    followed = session.exec(
        select(Channel)
        .join(Follow, col(Follow.channel_id) == col(Channel.id))
        .where(Follow.user_id == subject.id)
        .order_by(col(Channel.name))
    ).all()
    return ProfileOut(
        user=UserOut.model_validate(subject),
        posts=posts,
        channels=_channels_out(session, user, list(followed)),
    )


# --------------------------------------------------------------------------- channels


@app.get("/channels", response_model=list[ChannelOut])
def list_channels(
    session: SessionDep,
    user: UserDep,
    following: bool = Query(default=False, description="only the channels you follow"),
) -> list[ChannelOut]:
    statement = select(Channel).order_by(col(Channel.name))
    if following:
        statement = statement.join(Follow, col(Follow.channel_id) == col(Channel.id)).where(
            Follow.user_id == user.id
        )
    return _channels_out(session, user, list(session.exec(statement).all()))


@app.post("/channels", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
def create_channel(body: ChannelCreate, session: SessionDep, user: UserDep) -> ChannelOut:
    """Anyone can open a channel. The slug is derived from the name and must be free."""
    slug = _slugify(body.name)
    if not slug:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "the name needs at least one letter or digit"
        )
    if session.exec(select(Channel).where(Channel.slug == slug)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"channel {slug!r} already exists")

    channel = Channel(
        slug=slug, name=body.name.strip(), description=body.description.strip(), created_by=user.id
    )
    session.add(channel)
    # The creator follows it -- otherwise you open a channel and it is absent from
    # the one feed you actually read.
    session.commit()
    session.refresh(channel)
    session.add(Follow(user_id=user.id, channel_id=channel.id))
    session.commit()
    return _channels_out(session, user, [channel])[0]


@app.get("/channels/{slug}", response_model=ChannelOut)
def get_channel(slug: str, session: SessionDep, user: UserDep) -> ChannelOut:
    return _channels_out(session, user, [_get_channel(session, slug)])[0]


@app.post("/channels/{slug}/follow", response_model=ToggleOut)
def toggle_follow(slug: str, session: SessionDep, user: UserDep) -> ToggleOut:
    channel = _get_channel(session, slug)
    existing = session.exec(
        select(Follow).where(Follow.user_id == user.id, Follow.channel_id == channel.id)
    ).first()
    if existing is None:
        session.add(Follow(user_id=user.id, channel_id=channel.id))
        active = True
    else:
        session.delete(existing)
        active = False
    session.commit()
    count = session.exec(
        select(func.count()).select_from(Follow).where(Follow.channel_id == channel.id)
    ).one()
    return ToggleOut(active=active, count=count)


# --------------------------------------------------------------------------- feed


@app.get("/feed", response_model=FeedPage)
def feed(
    session: SessionDep,
    user: UserDep,
    cursor: str | None = Query(default=None, description="opaque; pass nextCursor from the last page"),
    limit: int = Query(default=10, ge=1, le=50),
    scope: Literal["all", "following"] = Query(
        default="all", description="'following' keeps only posts in channels you follow"
    ),
    channel: str | None = Query(default=None, description="channel slug"),
    author: str | None = Query(default=None, description="author user id"),
) -> FeedPage:
    """Newest first, keyset paginated so inserts during scrolling cannot duplicate a row.

    The three filters are the same query with an extra WHERE: the home feed, a
    channel's videos and a profile's posts are one endpoint, not three.
    """
    statement = select(Post).order_by(col(Post.created_at).desc(), col(Post.id).desc())

    if channel:
        statement = statement.where(Post.channel_id == _get_channel(session, channel).id)
    if author:
        statement = statement.where(Post.author_id == author)
    if scope == "following":
        # Empty on purpose when nothing is followed -- a "following" feed that quietly
        # shows everything is indistinguishable from a broken follow button.
        statement = statement.where(
            col(Post.channel_id).in_(select(Follow.channel_id).where(Follow.user_id == user.id))
        )

    if cursor:
        raw_ts, _, cursor_id = cursor.partition("|")
        try:
            cursor_ts = datetime.fromisoformat(raw_ts)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed cursor") from None
        statement = statement.where(
            (col(Post.created_at) < cursor_ts)
            | ((col(Post.created_at) == cursor_ts) & (col(Post.id) < cursor_id))
        )

    rows = session.exec(statement.limit(limit + 1)).all()
    page, has_more = rows[:limit], len(rows) > limit
    next_cursor = f"{page[-1].created_at.isoformat()}|{page[-1].id}" if page and has_more else None
    return FeedPage(items=_hydrate(session, user, list(page)), next_cursor=next_cursor)


@app.get("/posts/{post_id}", response_model=PostOut)
def get_post(post_id: str, session: SessionDep, user: UserDep) -> PostOut:
    post = _get_post(session, post_id)
    return _hydrate(session, user, [post])[0]


#: The one channel the system routes to on its own. A Slack thread IS an announcement,
#: so its explainer is pinned here rather than left to whatever the client asked for.
#: Matches `ANNOUNCEMENTS_SLUG` in scripts/seed.py.
ANNOUNCEMENTS_SLUG = "announcements"


def _is_slack_sourced(storyboard: dict[str, Any] | None) -> bool:
    """Whether a storyboard came from a Slack thread.

    Read off the storyboard's own `source`, not off a field the caller sets separately:
    the source is what the citations point at, so it cannot disagree with the content.
    """
    if not storyboard:
        return False
    source = storyboard.get("source")
    return isinstance(source, dict) and source.get("kind") == "slack"


def _announcements_channel(session: Session, created_by: str) -> Channel:
    """The Announcements channel, created on first use.

    Get-or-create rather than a 422 on a missing channel: the restriction must hold on a
    fresh database that was never seeded, and failing a finished render because a row is
    absent would throw away real work.

    Takes a user id rather than a ``User`` because the pipeline calls this too, and there
    it holds ``job.requester_id`` without a row loaded.
    """
    channel = session.exec(select(Channel).where(Channel.slug == ANNOUNCEMENTS_SLUG)).first()
    if channel is not None:
        return channel
    channel = Channel(
        slug=ANNOUNCEMENTS_SLUG,
        name="Announcements",
        description="Ships, launches and changes — straight from the thread that announced them.",
        created_by=created_by,
    )
    session.add(channel)
    session.commit()
    session.refresh(channel)
    return channel


@app.post("/posts", response_model=PostOut, status_code=status.HTTP_201_CREATED)
def create_post(body: PostCreate, session: SessionDep, user: UserDep) -> PostOut:
    if body.kind == "generated" and body.storyboard is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "generated posts need a storyboard")
    if body.kind == "clip" and not body.media_url:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "clip posts need a mediaUrl")
    if body.channel_id and session.get(Channel, body.channel_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no such channel")

    fields = body.model_dump()
    if _is_slack_sourced(body.storyboard):
        # Enforced here rather than trusted from the client, because a default the caller
        # can override is not a restriction. Whatever channel was asked for, a thread
        # becomes an announcement.
        fields["channel_id"] = _announcements_channel(session, user.id).id

    post = Post(author_id=user.id, **fields)
    session.add(post)
    session.commit()
    session.refresh(post)
    return _hydrate(session, user, [post])[0]


@app.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(post_id: str, session: SessionDep, user: UserDep) -> None:
    post = _get_post(session, post_id)
    if post.author_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the author can delete this post")
    # no cascade on SQLite by default, so clear the children explicitly
    for model in (Like, Save, Comment):
        session.exec(delete(model).where(model.post_id == post_id))
    session.delete(post)
    session.commit()


@app.post("/posts/{post_id}/like", response_model=ToggleOut)
def toggle_like(post_id: str, session: SessionDep, user: UserDep) -> ToggleOut:
    _get_post(session, post_id)
    return _toggle(session, Like, user, post_id)


@app.post("/posts/{post_id}/save", response_model=ToggleOut)
def toggle_save(post_id: str, session: SessionDep, user: UserDep) -> ToggleOut:
    _get_post(session, post_id)
    return _toggle(session, Save, user, post_id)


@app.post("/posts/{post_id}/view")
def register_view(post_id: str, session: SessionDep, user: UserDep) -> dict[str, int]:
    """Reach is the metric the pitch rests on, so it is counted from day one."""
    post = _get_post(session, post_id)
    post.views += 1
    session.add(post)
    session.commit()
    return {"views": post.views}


@app.get("/posts/{post_id}/comments", response_model=list[CommentOut])
def list_comments(post_id: str, session: SessionDep, user: UserDep) -> list[CommentOut]:
    _get_post(session, post_id)
    rows = session.exec(
        select(Comment).where(Comment.post_id == post_id).order_by(col(Comment.created_at).asc())
    ).all()
    authors = {
        u.id: u
        for u in session.exec(select(User).where(col(User.id).in_([c.author_id for c in rows]))).all()
    } if rows else {}
    return [
        CommentOut(id=c.id, text=c.text, created_at=c.created_at, author=UserOut.model_validate(authors[c.author_id]))
        for c in rows
    ]


@app.post("/posts/{post_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(post_id: str, body: CommentCreate, session: SessionDep, user: UserDep) -> CommentOut:
    _get_post(session, post_id)
    comment = Comment(post_id=post_id, author_id=user.id, text=body.text)
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return CommentOut(
        id=comment.id, text=comment.text, created_at=comment.created_at, author=UserOut.model_validate(user)
    )


@app.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: str, session: SessionDep, user: UserDep) -> None:
    comment = session.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "comment not found")
    if comment.author_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the author can delete this comment")
    session.delete(comment)
    session.commit()


@app.post("/uploads", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
def upload_media(user: UserDep, file: UploadFile = File(...)) -> UploadOut:
    """Accept a clip and return object metadata to reference from a post."""
    suffix = Path(file.filename or "clip.mp4").suffix.lower()
    if suffix not in {".mp4", ".webm", ".mov", ".m4v"}:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported extension {suffix!r}")
    if file.size is not None and file.size > settings.max_upload_bytes:
        mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"video must be {mb} MB or smaller")

    stored = store_upload(file, user.id, suffix)
    # Supabase hands back an absolute URL already; the local-disk fallback hands back
    # "/media/...", which resolves against the web app's origin and 404s there. One
    # pass through `_absolute_media` covers both without the caller knowing which
    # backend stored it.
    return UploadOut(
        media_url=_absolute_media(stored.media_url) or stored.media_url,
        storage_key=stored.storage_key,
    )


# --------------------------------------------------------------------------- pipeline


def _scaled(progress: int, span: tuple[int, int]) -> int:
    """Map the single-part 20-100 progress scale onto one part's slice of it."""
    lo, hi = span
    return lo + (progress - 20) * (hi - lo) // 80


def _render_and_publish(
    session: Session,
    job: Job,
    storyboard,
    *,
    required: bool = False,
    media_id: str | None = None,
    span: tuple[int, int] = (20, 100),
    channel_id: str | None = None,
) -> None:
    """Voice, render and publish. Advances voicing -> rendering -> published.

    :param required: the caller asked for a video specifically. Missing tooling is then an
        error, not something to paper over. Silently publishing a browser reel instead is
        what made "I asked for a video and got narration" look like a bug in the product
        rather than an ffmpeg that was never installed.
    :param media_id: distinct id for this part's work dir and stored MP4 when a job
        publishes several parts; without it part 2 would overwrite part 1's media.
    :param span: this part's slice of the job's 20-100 progress range.
    :param channel_id: channel the published post lands in, already resolved by the caller.

    With ``required`` false, missing tooling falls back to a storyboard-only post so a box
    without ffmpeg or Chromium still produces something playable. Rendering is imported
    lazily either way, so an absent optional dependency never blocks boot.
    """
    from .render import RenderUnavailable, render_from_voiced, voice_storyboard
    from .render.publish import publish_render, publish_storyboard_only

    work_dir = Path(settings.work_dir) / (media_id or job.id)
    try:
        job.state, job.progress, job.updated_at = "voicing", _scaled(45, span), utcnow()
        session.add(job)
        session.commit()
        voiced = voice_storyboard(storyboard, work_dir)

        job.state, job.progress, job.updated_at = "rendering", _scaled(80, span), utcnow()
        session.add(job)
        session.commit()
        result = render_from_voiced(storyboard, voiced, work_dir)

        publish_render(session, job, storyboard, result, media_id=media_id, channel_id=channel_id)
    except RenderUnavailable as exc:
        if required:
            raise RuntimeError(
                f"a video was requested but this box cannot render one: {exc}. "
                "Install ffmpeg and Playwright's Chromium, or generate a storyboard reel "
                "instead — the reel narrates in the browser and needs neither."
            ) from exc
        log.warning("render tooling unavailable (%s); publishing storyboard-only", exc)
        publish_storyboard_only(session, job, storyboard, channel_id=channel_id)

    # The storyboard now carries measured durations; keep the job's copy in step.
    job.storyboard = storyboard_to_json(storyboard)
    job.state, job.progress = "published", _scaled(100, span)


def _voice_reel(
    session: Session,
    job: Job,
    storyboard,
    *,
    media_id: str | None = None,
    span: tuple[int, int] = (20, 100),
) -> None:
    """Best-effort narration audio for a browser reel.

    The same kokoro voice a rendered MP4 gets, encoded per scene to AAC and served
    from ``/media``, so the reel plays a real voice instead of the Web Speech API.
    Never fails the job: missing ffmpeg, no TTS voice, or a failed encode just leaves
    ``audioUrl`` unset and the reel narrates in the browser exactly as before.
    ``media_id`` keys this part's scene audio when a job publishes several parts.

    The voicing and encoding themselves live in ``render.publish`` so the repair script
    re-voices old posts through exactly this path rather than a copy of it.
    """
    from .render.publish import voice_scenes_to_media

    key = media_id or job.id
    try:
        job.state, job.progress, job.updated_at = "voicing", _scaled(45, span), utcnow()
        session.add(job)
        session.commit()

        if not voice_scenes_to_media(storyboard, Path(settings.work_dir) / key, key):
            log.info("no reel audio for %s; keeping Web Speech narration", job.id)
    except Exception as exc:
        log.warning("reel voicing failed (%s); publishing without audio", exc)
        for scene in storyboard.scenes:
            scene.audio_url = None


def _run_job(job_id: str, body: GenerateRequest) -> None:
    """Background worker. Owns its own session; the request's is already closed."""
    from .models import _engine

    with Session(_engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        # Part 1's storyboard, kept out of the loop so the tail below can restore it on
        # every path. A multi-part job overwrites job.storyboard once per part while it
        # runs, and the last part's is the wrong one to leave behind: job.post_id points
        # at part 1, so the two would describe different videos.
        first_storyboard: dict[str, Any] | None = None
        try:
            text, doc_title, doc_url = body.input, body.doc_title, body.doc_url

            if body.kind == "aidoc" and body.doc_id:
                try:
                    doc = fetch_doc(body.doc_id)
                    text = doc.to_prompt_text()
                    doc_title = doc_title or doc.title
                    doc_url = doc_url or doc.url
                except AidocsUnavailable as exc:
                    # pasted text is the fallback; only fail outright if there is none
                    log.warning("aidocs fetch failed for %s: %s", body.doc_id, exc)
                    if not body.input.strip():
                        raise RuntimeError(f"could not read {body.doc_id}: {exc}") from exc

            elif body.kind == "slack" and body.slack_url:
                # No pasted-text fallback here on purpose: text pasted out of Slack has
                # not been through the scrubber, and a thread is the one source where
                # that matters most.
                try:
                    thread = fetch_thread(body.slack_url)
                except SlackUnavailable as exc:
                    raise RuntimeError(f"could not read that thread: {exc}") from exc
                if not thread.is_structured:
                    raise RuntimeError(
                        f"that thread is too thin to explain — {len(thread.sections)} usable "
                        f"message(s) from {len(thread.participants)} participant(s)"
                    )
                text = thread.to_prompt_text()
                doc_title = doc_title or thread.title
                doc_url = doc_url or thread.url
                if thread.redactions:
                    log.info("job %s: redacted %s before the model", job_id, thread.redactions)

            if not text.strip():
                raise RuntimeError("nothing to generate from")

            job.state, job.progress, job.updated_at = "scripting", 10, utcnow()
            session.add(job)
            session.commit()

            # An over-long source is condensed first, keeping its headings verbatim so
            # citations still resolve. Everything downstream then reads a document that
            # fits, instead of a fragment truncated mid-table. No-op below the
            # threshold, and it falls back to the original text on any failure.
            text = run_reduce_stage(text=text, doc_title=doc_title)

            # One planning call decides whether this source is one video or up to three
            # logically segregated parts, each published as its own post. Planning can
            # only widen a job, never fail it: anything going wrong collapses to 1 part.
            parts = run_plan_stage(kind=body.kind, text=text, doc_title=doc_title)
            total = len(parts)
            first_post_id: str | None = None

            # Where the finished post(s) land. A Slack thread IS the announcement, so that
            # is where its explainer goes whatever was asked for — the same rule
            # `create_post` enforces, applied here because the pipeline is what creates
            # these posts. Resolved once: every part of a multi-part job shares a channel.
            channel_id = (
                _announcements_channel(session, job.requester_id).id
                if body.kind == "slack"
                else body.channel_id
            )

            for index, part in enumerate(parts, 1):
                # Each part gets an equal slice of the 20-100 progress range, and its
                # own media id so part 2's MP4 or scene audio cannot overwrite part 1's.
                span = (20 + (index - 1) * 80 // total, 20 + index * 80 // total)
                media_id = job.id if total == 1 else f"{job.id}p{index}"
                try:
                    job.state, job.progress, job.updated_at = "scripting", span[0], utcnow()
                    session.add(job)
                    session.commit()

                    storyboard = run_script_stage(
                        kind=body.kind,
                        text=text,
                        doc_id=body.doc_id,
                        doc_title=doc_title,
                        doc_url=doc_url,
                        style=body.format,
                        part={**part, "index": index, "total": total} if total > 1 else None,
                    )

                    # Stored in our INTERNAL shape: the feed's scene components dispatch on
                    # `scene.type` and read `cite`, so this column must never hold the render
                    # contract's `visual.kind` shape. See render_contract.py.
                    job.storyboard = storyboard_to_json(storyboard)

                    # The handoff. Steps 3 and 4 run on the same box, so the seam is a file on
                    # disk, not an HTTP call to our own API. Written even on the browser-reel
                    # path, so the voice and render stages have something to pick up whenever
                    # they are wired in, and so a bad projection surfaces now rather than later.
                    try:
                        write_bundle(media_id, storyboard)
                    except RenderContractInvalid as invalid:
                        # Not fatal: the browser reel plays from job.storyboard regardless. But
                        # it means this storyboard cannot become an MP4, and silence here would
                        # turn that into a mystery during rendering.
                        log.error("job %s cannot be rendered to MP4: %s", job_id, invalid.errors)

                    if body.format == "video":
                        _render_and_publish(
                            session, job, storyboard, required=True, media_id=media_id,
                            span=span, channel_id=channel_id,
                        )
                    else:
                        # A reel is the storyboard itself, so rendering is skipped. Narration is
                        # still pre-generated when the box can voice it — the same kokoro track an
                        # MP4 gets — so the browser plays real audio instead of the Web Speech
                        # API. Best-effort: without it the reel publishes exactly as before.
                        from .render.publish import publish_storyboard_only

                        _voice_reel(session, job, storyboard, media_id=media_id, span=span)
                        publish_storyboard_only(session, job, storyboard, channel_id=channel_id)
                        # Voicing stamped durations and audio URLs; keep the job's copy in step.
                        job.storyboard = storyboard_to_json(storyboard)
                        job.state, job.progress = "published", _scaled(100, span)
                except Exception as exc:
                    if total == 1:
                        raise
                    # Parts already published stay published; the error names what failed.
                    raise RuntimeError(
                        f"part {index}/{total} ({part['title']!r}) failed"
                        + (f" after {index - 1} part(s) were published" if first_post_id else "")
                        + f": {exc}"
                    ) from exc
                first_post_id = first_post_id or job.post_id
                # Captured after the part finished, so it is the voiced copy with measured
                # durations rather than the one written before the audio existed.
                first_storyboard = first_storyboard or job.storyboard

            # Publishing set job.post_id per part; the web app navigates to it, and a
            # multi-part job should land the viewer on part 1.
            job.post_id = first_post_id
        except StoryboardInvalid as invalid:
            job.state, job.error = "failed", "; ".join(invalid.errors)
            log.warning("job %s failed validation: %s", job_id, invalid.errors)
        except Exception as exc:
            job.state, job.error = "failed", str(exc)
            log.exception("job %s failed", job_id)

        # Last write wins on this column, and the loop wrote once per part. Put part 1's
        # back, including when a later part failed — job.post_id is part 1's post, and the
        # storyboard beside it has to be the same video.
        if first_storyboard is not None:
            job.storyboard = first_storyboard
        job.updated_at = utcnow()
        session.add(job)
        session.commit()


@app.post("/generate", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def generate(
    body: GenerateRequest,
    background: BackgroundTasks,
    session: SessionDep,
    user: UserDep,
) -> Job:
    """Queue a storyboard generation. Poll ``GET /jobs/{id}`` for the states.

    Returns 202 rather than blocking: the state sequence is what the web app shows
    while it waits, which is the difference between a progress bar and dead air.
    """
    if body.kind == "aidoc" and not body.doc_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "aidoc generation needs a docId")
    if body.kind == "topic" and len(body.input.strip()) < 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "topic generation needs input")
    if body.kind == "slack":
        if not body.slack_url:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "slack generation needs a slackUrl"
            )
        # Validated here, not in the worker: a bad link should be a 422 the caller sees,
        # not a job that fails a second later. The parsed ref is otherwise unused —
        # WHICH Slack channel a thread came from no longer gates anything. What is
        # restricted is where the result lands on our side; see `create_post`.
        try:
            parse_permalink(body.slack_url)
        except SlackUnavailable as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    if body.channel_id and session.get(Channel, body.channel_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no such channel")

    # `input` is empty for an aidoc or a Slack thread — the source is the id or the
    # permalink — so recording only `input` left every document-backed job with no
    # trace of WHICH document it was for, and a failure could not be reproduced.
    provenance = body.doc_id or body.slack_url or body.input
    job = Job(
        requester_id=user.id,
        source_kind=body.kind,
        source_input=(provenance or "")[:2000],
        format=body.format,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    background.add_task(_run_job, job.id, body)
    return job


@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: SessionDep, user: UserDep) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job


# ------------------------------------------------------------------- render handoff


def _render_file(stored: dict[str, Any] | None, what: str) -> dict[str, Any]:
    """Project a stored internal storyboard onto the renderer's schema.

    Projected on read rather than stored: the renderer's schema is theirs to change,
    and re-deriving from the internal storyboard costs nothing at feed scale while a
    stored copy would go stale the moment their version moves.
    """
    if not stored:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} has no storyboard")
    try:
        payload, _ = emit(Storyboard.model_validate(stored))
    except (RenderContractInvalid, StoryboardInvalid) as invalid:
        # Our bug, not the renderer's: something got stored that cannot be projected.
        log.error("cannot project %s onto the render contract: %s", what, invalid.errors)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"error": "storyboard cannot be rendered", "problems": invalid.errors},
        ) from invalid
    return payload


@app.get("/posts/{post_id}/storyboard.json")
def post_render_storyboard(post_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
    """``storyboard.json`` for the renderer. The only thing that crosses the boundary."""
    post = session.get(Post, post_id)
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "post not found")
    return _render_file(post.storyboard, "post")


@app.get("/jobs/{job_id}/storyboard.json")
def job_render_storyboard(job_id: str, session: SessionDep, user: UserDep) -> dict[str, Any]:
    """Same file, straight off a finished job, before it is ever posted."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return _render_file(job.storyboard, "job")
