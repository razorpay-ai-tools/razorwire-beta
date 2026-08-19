"""Media object storage.

Videos do not belong in Postgres. Store the bytes in Supabase Storage when it is
configured; keep local disk as the no-config fallback for demos.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import HTTPException, UploadFile, status

from .config import settings
from .models import utcnow


MIME_BY_SUFFIX = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
}


@dataclass(frozen=True)
class StoredMedia:
    media_url: str
    storage_key: str


def _object_key(user_id: str, suffix: str) -> str:
    stamp = utcnow().strftime("%Y/%m/%d/%H%M%S%f")
    return f"clips/{user_id}/{stamp}{suffix}"


def _public_url(key: str) -> str:
    base = settings.supabase_url.rstrip("/")
    bucket = settings.supabase_storage_bucket
    return f"{base}/storage/v1/object/public/{bucket}/{key}"


def _store_supabase(file: UploadFile, user_id: str, suffix: str) -> StoredMedia:
    key = _object_key(user_id, suffix)
    base = settings.supabase_url.rstrip("/")
    bucket = settings.supabase_storage_bucket
    url = f"{base}/storage/v1/object/{bucket}/{key}"
    headers = {
        "authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key,
        "content-type": file.content_type or MIME_BY_SUFFIX.get(suffix, "application/octet-stream"),
        "x-upsert": "false",
    }
    try:
        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, content=file.file)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Supabase Storage upload failed: {exc.response.status_code}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Supabase Storage upload failed: {exc}") from exc

    return StoredMedia(media_url=_public_url(key) if settings.supabase_storage_public else url, storage_key=key)


def _store_local(file: UploadFile, user_id: str, suffix: str) -> StoredMedia:
    media_dir = Path(settings.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    name = f"{user_id}_{utcnow().strftime('%Y%m%d%H%M%S%f')}{suffix}"
    destination = media_dir / name
    with destination.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return StoredMedia(media_url=f"/media/{name}", storage_key=f"local/{name}")


def store_upload(file: UploadFile, user_id: str, suffix: str) -> StoredMedia:
    if settings.supabase_storage_enabled:
        return _store_supabase(file, user_id, suffix)
    return _store_local(file, user_id, suffix)
