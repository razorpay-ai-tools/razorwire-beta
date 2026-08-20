"""Publish a rendered video (or a storyboard-only reel) as a feed Post.

The MP4 goes to media storage (Supabase when configured, local disk otherwise) and
the DB row keeps only the pointer plus metadata. Setting ``job.post_id`` is what the
web app polls for: `GeneratePanel` navigates to the post the moment it appears.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from sqlmodel import Session

from ..config import settings
from ..models import Job, Post, utcnow
from ..pipeline import storyboard_to_json
from ..storyboard import Storyboard
from .pipeline import RenderResult

log = logging.getLogger(__name__)


def _store_local(mp4: Path, job_id: str) -> tuple[str, str]:
    media_dir = Path(settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    name = f"{job_id}.mp4"
    (media_dir / name).write_bytes(mp4.read_bytes())
    return f"/media/{name}", f"local/{name}"


def _store_supabase(mp4: Path, job_id: str) -> tuple[str, str]:
    base = settings.supabase_url.rstrip("/")
    bucket = settings.supabase_storage_bucket
    key = f"generated/{utcnow().strftime('%Y/%m/%d')}/{job_id}.mp4"
    url = f"{base}/storage/v1/object/{bucket}/{key}"
    headers = {
        "authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key,
        "content-type": "video/mp4",
        "x-upsert": "true",
    }
    with httpx.Client(timeout=120) as client:
        client.post(url, headers=headers, content=mp4.read_bytes()).raise_for_status()
    public = f"{base}/storage/v1/object/public/{bucket}/{key}"
    return (public if settings.supabase_storage_public else url), key


def store_mp4(mp4: Path, job_id: str) -> tuple[str, str]:
    """Persist the MP4, returning ``(media_url, storage_key)``."""
    if settings.supabase_storage_enabled:
        return _store_supabase(mp4, job_id)
    return _store_local(mp4, job_id)


def _create_post(
    session: Session,
    job: Job,
    sb: Storyboard,
    *,
    media_url: str | None,
    storage_key: str | None,
    duration_ms: int | None,
    channel_id: str | None = None,
) -> Post:
    post = Post(
        author_id=job.requester_id,
        title=sb.meta.title,
        tags=list(sb.meta.tags),
        kind="generated",
        channel_id=channel_id,
        media_url=media_url,
        storage_key=storage_key,
        thumbnail_url=None,  # the <video> uses its first frame as the poster
        duration_ms=duration_ms,
        storyboard=storyboard_to_json(sb),
        source_doc_id=sb.source.doc_id,
    )
    session.add(post)
    session.commit()
    session.refresh(post)
    job.post_id = post.id
    session.add(job)
    session.commit()
    return post


def publish_render(
    session: Session,
    job: Job,
    sb: Storyboard,
    result: RenderResult,
    *,
    media_id: str | None = None,
    channel_id: str | None = None,
) -> Post:
    """Store the MP4 and create the generated Post that plays it.

    ``media_id`` distinguishes the parts of a multi-part job; storing every part under
    ``job.id`` would leave one file that each part silently overwrites."""
    media_url, storage_key = store_mp4(result.mp4_path, media_id or job.id)
    post = _create_post(
        session, job, sb,
        media_url=media_url, storage_key=storage_key, duration_ms=result.duration_ms,
        channel_id=channel_id,
    )
    log.info("published render as post %s (%s)", post.id, media_url)
    return post


def publish_storyboard_only(
    session: Session, job: Job, sb: Storyboard, *, channel_id: str | None = None
) -> Post:
    """Fallback when rendering tooling is unavailable: publish the storyboard so the
    browser reel still plays. No MP4, so no ``media_url``."""
    post = _create_post(
        session, job, sb,
        media_url=None, storage_key=None, duration_ms=None, channel_id=channel_id,
    )
    log.info("published storyboard-only post %s (no mp4)", post.id)
    return post
