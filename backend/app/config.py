"""Settings, read from the environment or backend/.env."""

from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./razorwire.db"

    # web app origin, for CORS
    web_origin: str = "http://localhost:3000"

    #: This API's own public origin. Uploaded media is served by THIS service, so a
    #: relative "/media/..." would resolve against the web app and 404. Responses carry
    #: absolute URLs instead, which keeps every client correct without each one having
    #: to know where media lives.
    public_base_url: str = "http://localhost:8000"

    # --- auth -----------------------------------------------------------------
    google_client_id: str = ""
    allowed_hd: str = "razorpay.com"
    #: Local escape hatch. When set and no bearer token is presented, requests are
    #: treated as this user. Leave empty in anything shared.
    dev_auth_email: str = ""

    # --- pipeline -------------------------------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # --- slack ingestion ------------------------------------------------------
    #: Restored here for the same reason as `work_dir` below: PR #5 added these and
    #: `slack.py` reads them, but PR #4's config.py landed without them.
    #:
    #: Bot token (``xoxb-``). Needs scopes: channels:history, groups:history,
    #: channels:read, users:read. The bot must also be invited to any channel it
    #: reads — Slack returns `not_in_channel` otherwise.
    slack_bot_token: str = ""
    #: Channels we are allowed to ingest from, comma-separated ids or names. Empty
    #: means none: an allow-list that defaults to "everything" is not an allow-list.
    slack_allowed_channels: str = ""

    @property
    def slack_allow_list(self) -> frozenset[str]:
        raw = (self.slack_allowed_channels or "").split(",")
        return frozenset(part.strip().lstrip("#") for part in raw if part.strip())

    # --- storage --------------------------------------------------------------
    #: Uploads land here when Supabase Storage is not configured.
    media_dir: str = "./.storage"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "razorwire-videos"
    supabase_storage_public: bool = True
    max_upload_bytes: int = 50 * 1024 * 1024

    #: Scratch space for one generation run: storyboard.json, scene wavs, scene pngs.
    #: Deliberately NOT mounted at a URL — it holds intermediate work derived from
    #: internal documents, and only the finished MP4 is copied into media_dir.
    #:
    #: Restored here: PR #5 added it and `render_contract.py` reads it, but PR #4's
    #: config.py landed without it, so `main` fails its own render-contract tests.
    work_dir: str = "./.work"

    # --- render (MP4 pipeline) ------------------------------------------------
    render_fps: int = 30
    render_width: int = 1080
    render_height: int = 1920
    #: TTS backend: "auto" prefers Kokoro, falls back to macOS `say`, then silence.
    render_tts: str = "auto"
    kokoro_voice: str = "af_heart"
    #: Hard cap on a single scene's spoken length so one runaway scene cannot
    #: stretch the render; longer scenes are clamped.
    render_scene_max_ms: int = 15000

    @property
    def supabase_storage_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key and self.supabase_storage_bucket)

    @property
    def dev_auth_enabled(self) -> bool:
        return bool(self.dev_auth_email)


settings = Settings()
