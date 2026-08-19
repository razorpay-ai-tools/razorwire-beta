"""Razorwire API.

The surface the web app talks to: an Instagram-shaped feed (posts, likes, saves,
comments, views) plus the storyboard generation pipeline.

Run it:  uv run uvicorn app.main:app --reload --port 8000
Docs at: http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import shutil
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
from .models import Comment, Job, Like, Post, Save, User, get_session, init_db, utcnow
from .pipeline import run_script_stage, storyboard_to_json
from .render_contract import RenderContractInvalid, emit, write_bundle
from .slack import SlackUnavailable, fetch_thread, parse_permalink
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


class PostCreate(_Out):
    title: str = Field(min_length=3, max_length=120)
    description: str = ""
    team: str = ""
    category: str = "Product"
    tags: list[str] = Field(default_factory=list)
    accent: str = ""
    kind: Literal["clip", "generated"] = "clip"
    media_url: str | None = None
    duration_ms: int | None = None
    storyboard: dict[str, Any] | None = None
    source_doc_id: str | None = None


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
    duration_ms: int | None
    storyboard: dict[str, Any] | None
    source_doc_id: str | None
    views: int
    created_at: datetime
    author: UserOut

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


class JobOut(_Out):
    id: str
    state: str
    progress: int
    error: str | None
    storyboard: dict[str, Any] | None
    post_id: str | None
    created_at: datetime
    updated_at: datetime


class UploadOut(_Out):
    media_url: str


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


def _to_out(post: Post, author: User, counts: dict[str, int], liked: bool, saved: bool) -> PostOut:
    return PostOut(
        **post.model_dump(),
        author=UserOut.model_validate(author),
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
    return [
        _to_out(p, authors[p.author_id], counts[p.id], p.id in liked, p.id in saved)
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


# --------------------------------------------------------------------------- routes


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/me", response_model=UserOut)
def me(user: UserDep) -> User:
    return user


@app.get("/feed", response_model=FeedPage)
def feed(
    session: SessionDep,
    user: UserDep,
    cursor: str | None = Query(default=None, description="opaque; pass nextCursor from the last page"),
    limit: int = Query(default=10, ge=1, le=50),
) -> FeedPage:
    """Newest first, keyset paginated so inserts during scrolling cannot duplicate a row."""
    statement = select(Post).order_by(col(Post.created_at).desc(), col(Post.id).desc())
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


@app.post("/posts", response_model=PostOut, status_code=status.HTTP_201_CREATED)
def create_post(body: PostCreate, session: SessionDep, user: UserDep) -> PostOut:
    if body.kind == "generated" and body.storyboard is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "generated posts need a storyboard")
    if body.kind == "clip" and not body.media_url:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "clip posts need a mediaUrl")

    post = Post(author_id=user.id, **body.model_dump())
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
    """Accept a clip and return a URL to reference from a post.

    ponytail: the binary is proxied through the app onto local disk. That is fine for
    one box and it avoids a day lost to S3 presign CORS. Move to a presigned PUT when
    the feed is served from more than one machine.
    """
    suffix = Path(file.filename or "clip.mp4").suffix.lower()
    if suffix not in {".mp4", ".webm", ".mov", ".m4v"}:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"unsupported extension {suffix!r}")

    name = f"{user.id}_{utcnow().strftime('%Y%m%d%H%M%S%f')}{suffix}"
    destination = MEDIA_DIR / name
    with destination.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return UploadOut(media_url=f"/media/{name}")


# --------------------------------------------------------------------------- pipeline


def _run_job(job_id: str, body: GenerateRequest) -> None:
    """Background worker. Owns its own session; the request's is already closed."""
    from .models import _engine

    with Session(_engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return
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

            job.state, job.progress, job.updated_at = "scripting", 20, utcnow()
            session.add(job)
            session.commit()

            storyboard = run_script_stage(
                kind=body.kind,
                text=text,
                doc_id=body.doc_id,
                doc_title=doc_title,
                doc_url=doc_url,
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
                write_bundle(job.id, storyboard)
            except RenderContractInvalid as invalid:
                # Not fatal: the browser reel plays from job.storyboard regardless. But
                # it means this storyboard cannot become an MP4, and silence here would
                # turn that into a mystery during rendering.
                log.error("job %s cannot be rendered to MP4: %s", job_id, invalid.errors)

            job.state, job.progress = "published", 100
        except StoryboardInvalid as invalid:
            job.state, job.error = "failed", "; ".join(invalid.errors)
            log.warning("job %s failed validation: %s", job_id, invalid.errors)
        except Exception as exc:
            job.state, job.error = "failed", str(exc)
            log.exception("job %s failed", job_id)

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
        # Validated here, not in the worker: a bad link or a channel we are not allowed
        # to read should be a 422 the caller sees, not a job that fails a second later.
        try:
            ref = parse_permalink(body.slack_url)
        except SlackUnavailable as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        if ref.channel not in settings.slack_allow_list:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"{ref.channel} is not in SLACK_ALLOWED_CHANNELS. Ingesting a channel is "
                "opt-in, because a thread's participants did not write it for the feed.",
            )

    job = Job(requester_id=user.id, source_kind=body.kind, source_input=body.input[:2000])
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
