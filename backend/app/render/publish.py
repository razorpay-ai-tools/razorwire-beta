"""Publish a rendered video (or a storyboard-only reel) as a feed Post.

The MP4 goes to media storage (Supabase when configured, local disk otherwise) and
the DB row keeps only the pointer plus metadata. Setting ``job.post_id`` is what the
web app polls for: `GeneratePanel` navigates to the post the moment it appears.

``voice_scenes_to_media`` lives here too: it is the other thing this module owns, a
storyboard turned into files under ``media_dir``. Two callers share it — the generate
path (``main._voice_reel``) and the repair script (``scripts/revoice.py``).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import wave
from pathlib import Path

import httpx
from sqlmodel import Session

from ..config import settings
from ..models import Job, Post, utcnow
from ..pipeline import storyboard_to_json
from ..storyboard import Storyboard
from .pipeline import RenderResult, voice_storyboard

log = logging.getLogger(__name__)


def _tts_is_silent(voiced) -> bool:
    """True when every spoken track is all zero samples — no TTS engine produced a
    voice, and a silent audio track is strictly worse than the Web Speech fallback."""
    for spoken in voiced:
        try:
            with wave.open(str(spoken.wav_path), "rb") as handle:
                if any(handle.readframes(handle.getnframes())):
                    return False
        except Exception:
            continue
    return True


def voice_scenes_to_media(sb: Storyboard, work_dir: Path, media_id: str) -> list:
    """Speak every scene, encode each to AAC under ``media_dir``, stamp the storyboard.

    Leaves ``durationMs`` (measured off the wav) and ``audioUrl`` on every scene and
    returns the voiced scenes, which the interactive composition is built from. Returns
    an empty list *without touching the storyboard* when there is nothing
    worth playing — no ffmpeg to encode with, or no TTS engine, in which case the reel
    narrates with the Web Speech API exactly as it did before. Raises only on a failed
    encode, which the caller decides what to do about.

    ``media_id`` names the files (``<media_id>_scene<n>.m4a``), so it has to be unique
    per published thing: a job part id on the generate path, a post id on the repair
    path. Re-running with the same id overwrites in place, which is what makes the
    repair script idempotent.
    """
    if shutil.which("ffmpeg") is None:
        return []
    voiced = voice_storyboard(sb, work_dir)
    if _tts_is_silent(voiced):
        return []
    media_dir = Path(settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    for scene, spoken in zip(sb.scenes, voiced):
        name = f"{media_id}_scene{spoken.index}.m4a"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(spoken.wav_path), "-c:a", "aac", "-b:a", "96k",
             str(media_dir / name)],
            check=True, capture_output=True, timeout=120,
        )
        scene.audio_url = f"/media/{name}"
    return voiced


def _store_local(mp4: Path, job_id: str) -> tuple[str, str]:
    media_dir = Path(settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    name = f"{job_id}.mp4"
    (media_dir / name).write_bytes(mp4.read_bytes())
    return f"/media/{name}", f"local/{name}"


def _store_poster(jpg: Path, job_id: str) -> str | None:
    """Persist the poster next to the MP4, returning its URL.

    Best-effort by design: the poster is also baked into frame 0 of the MP4, so a
    failure here costs the explicit ``<video poster>`` and nothing else — the feed
    still shows the right still.
    """
    try:
        if settings.supabase_storage_enabled:
            base = settings.supabase_url.rstrip("/")
            bucket = settings.supabase_storage_bucket
            key = f"generated/{utcnow().strftime('%Y/%m/%d')}/{job_id}.jpg"
            url = f"{base}/storage/v1/object/{bucket}/{key}"
            headers = {
                "authorization": f"Bearer {settings.supabase_service_role_key}",
                "apikey": settings.supabase_service_role_key,
                "content-type": "image/jpeg",
                "x-upsert": "true",
            }
            with httpx.Client(timeout=60) as client:
                client.post(url, headers=headers, content=jpg.read_bytes()).raise_for_status()
            if settings.supabase_storage_public:
                return f"{base}/storage/v1/object/public/{bucket}/{key}"
            return url

        media_dir = Path(settings.media_dir)
        media_dir.mkdir(parents=True, exist_ok=True)
        name = f"{job_id}.jpg"
        (media_dir / name).write_bytes(jpg.read_bytes())
        return f"/media/{name}"
    except Exception as exc:
        log.warning("could not store the poster for %s: %s", job_id, exc)
        return None


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
    thumbnail_url: str | None = None,
    interactive_url: str | None = None,
) -> Post:
    post = Post(
        author_id=job.requester_id,
        title=sb.meta.title,
        tags=list(sb.meta.tags),
        kind="generated",
        channel_id=channel_id,
        media_url=media_url,
        storage_key=storage_key,
        # Falling back to the <video>'s own first frame is what made every generated
        # post a black tile: both engines open on a fade from black. render/poster.py
        # picks a real frame and bakes it in as frame 0 too, so players that ignore
        # this attribute still get the right still.
        thumbnail_url=thumbnail_url,
        interactive_url=interactive_url,
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
    interactive_url: str | None = None,
) -> Post:
    """Store the MP4 and create the generated Post that plays it.

    ``media_id`` distinguishes the parts of a multi-part job; storing every part under
    ``job.id`` would leave one file that each part silently overwrites."""
    media_id = media_id or job.id
    media_url, storage_key = store_mp4(result.mp4_path, media_id)
    thumbnail_url = (
        _store_poster(result.poster_path, media_id)
        if result.poster_path and result.poster_path.is_file()
        else None
    )
    post = _create_post(
        session, job, sb,
        media_url=media_url, storage_key=storage_key, duration_ms=result.duration_ms,
        channel_id=channel_id, thumbnail_url=thumbnail_url, interactive_url=interactive_url,
    )
    log.info("published render as post %s (%s)", post.id, media_url)
    return post


def publish_storyboard_only(
    session: Session,
    job: Job,
    sb: Storyboard,
    *,
    channel_id: str | None = None,
    interactive_url: str | None = None,
) -> Post:
    """Fallback when rendering tooling is unavailable: publish the storyboard so the
    browser reel still plays. No MP4, so no ``media_url``."""
    post = _create_post(
        session, job, sb,
        media_url=None, storage_key=None, duration_ms=None, channel_id=channel_id,
        interactive_url=interactive_url,
    )
    log.info("published storyboard-only post %s (no mp4)", post.id)
    return post
