"""Database tables and session handling.

Eight tables. Postgres is the shared-store path; SQLite stays the local fallback.
Reaction counts are derived with COUNT rather than kept in denormalised columns: at
feed scale it is free, and a counter that cannot drift is one less thing to debug on
demo day.

ponytail: SQLModel create_all, no Alembic. Add migrations when the schema has to
survive real deploy history instead of a fresh hackathon database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint, inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine

from .config import settings


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(default_factory=lambda: new_id("usr"), primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str
    picture: str | None = None
    #: free text on the profile; the only field a person can edit about themselves
    bio: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Channel(SQLModel, table=True):
    """A topic anyone can create and anyone can follow. Posts belong to at most one.

    The slug is the public handle -- the feed filters and the channel view address a
    channel by slug, so it is unique and derived once at creation rather than editable.
    """

    __tablename__ = "channels"

    id: str = Field(default_factory=lambda: new_id("chn"), primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    description: str = ""
    created_by: str = Field(index=True, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)


class Follow(SQLModel, table=True):
    """Who follows which channel. The following feed is a join over this table."""

    __tablename__ = "follows"
    __table_args__ = (UniqueConstraint("user_id", "channel_id", name="uq_follow"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, foreign_key="users.id")
    channel_id: str = Field(index=True, foreign_key="channels.id")
    created_at: datetime = Field(default_factory=utcnow)


class Post(SQLModel, table=True):
    __tablename__ = "posts"

    id: str = Field(default_factory=lambda: new_id("post"), primary_key=True)
    author_id: str = Field(index=True, foreign_key="users.id")

    title: str
    description: str = ""
    team: str = ""
    category: str = "Product"
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    accent: str = ""

    #: the channel this was posted to, when the author chose one
    channel_id: str | None = Field(default=None, index=True, foreign_key="channels.id")

    #: "clip" for an uploaded video, "generated" for a pipeline storyboard
    kind: str = Field(default="clip", index=True)
    #: uploaded video, or the rendered MP4 export once one exists
    media_url: str | None = None
    storage_key: str | None = None
    thumbnail_url: str | None = None
    duration_ms: int | None = None

    #: full storyboard for kind="generated"; the web app renders scenes from this
    storyboard: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    source_doc_id: str | None = Field(default=None, index=True)

    views: int = 0
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Like(SQLModel, table=True):
    __tablename__ = "likes"
    __table_args__ = (UniqueConstraint("user_id", "post_id", name="uq_like"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, foreign_key="users.id")
    post_id: str = Field(index=True, foreign_key="posts.id")
    created_at: datetime = Field(default_factory=utcnow)


class Save(SQLModel, table=True):
    __tablename__ = "saves"
    __table_args__ = (UniqueConstraint("user_id", "post_id", name="uq_save"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, foreign_key="users.id")
    post_id: str = Field(index=True, foreign_key="posts.id")
    created_at: datetime = Field(default_factory=utcnow)


class Comment(SQLModel, table=True):
    __tablename__ = "comments"

    id: str = Field(default_factory=lambda: new_id("cmt"), primary_key=True)
    post_id: str = Field(index=True, foreign_key="posts.id")
    author_id: str = Field(index=True, foreign_key="users.id")
    text: str
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Job(SQLModel, table=True):
    """One storyboard generation run.

    States: queued -> scripting -> voicing -> rendering -> published | failed.
    The web app polls this and shows the stages, which is what turns the wait into
    part of the demo instead of dead air.
    """

    __tablename__ = "jobs"

    id: str = Field(default_factory=lambda: new_id("job"), primary_key=True)
    requester_id: str = Field(index=True, foreign_key="users.id")

    state: str = Field(default="queued", index=True)
    progress: int = 0
    error: str | None = None

    source_kind: str = "topic"
    source_input: str = ""
    storyboard: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    post_id: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


def _engine_kwargs(url: str) -> dict[str, Any]:
    if not url.startswith("sqlite"):
        return {"pool_pre_ping": True}
    # background jobs and request handlers touch the same connection pool
    kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
    # ":memory:" gives every new connection its own empty database, so tables created
    # at startup are invisible to request sessions. One shared connection fixes it.
    if url in {"sqlite://", "sqlite:///:memory:"}:
        kwargs["poolclass"] = StaticPool
    return kwargs


def _database_url(raw: str) -> str:
    if raw.startswith("postgresql+"):
        return raw
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+psycopg://", 1)
    return raw


_database_url_value = _database_url(settings.database_url)
_engine = create_engine(_database_url_value, echo=False, **_engine_kwargs(_database_url_value))


def init_db() -> None:
    SQLModel.metadata.create_all(_engine)
    _ensure_post_media_columns()


def _ensure_post_media_columns() -> None:
    existing = {column["name"] for column in inspect(_engine).get_columns("posts")}
    missing = [name for name in ("storage_key", "thumbnail_url") if name not in existing]
    if not missing:
        return
    # ponytail: tiny additive migration. Replace with Alembic when schema history matters.
    with _engine.begin() as conn:
        for name in missing:
            conn.execute(text(f"alter table posts add column {name} varchar"))


def get_session() -> Session:
    """FastAPI dependency. Yields a session and always closes it."""
    with Session(_engine) as session:
        yield session
