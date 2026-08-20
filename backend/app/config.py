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
    #: Razorpay's LiteLLM gateway. It serves Anthropic's own `/v1/messages` shape and
    #: translates it to whatever model is asked for, so the script stage keeps using the
    #: `anthropic` SDK and no second client or dependency is needed. Point this at
    #: nothing to talk to api.anthropic.com directly instead.
    llm_base_url: str = "https://llm-gateway.razorpay.com"
    #: Gateway key. Preferred over `anthropic_api_key`, which stays for anyone holding a
    #: direct Anthropic key rather than a gateway one.
    litellm_api_key: str = ""
    anthropic_api_key: str = ""
    #: Whatever the gateway routes. `glm-5p2` today; a Claude model here would also work,
    #: since the gateway speaks the same wire format either way.
    llm_model: str = "glm-5p2"

    # --- slack ingestion ------------------------------------------------------
    #: Bot token (``xoxb-``). Read-only: the integration calls conversations.replies,
    #: conversations.info and users.info over GET and nothing else, so the scopes are
    #: channels:history, groups:history, channels:read, users:read — no write scope.
    #: The bot must also be invited to any channel it reads, or Slack returns
    #: `not_in_channel`.
    #:
    #: There is deliberately no channel allow-list. Which Slack channel a thread came
    #: from no longer gates ingestion; the restriction that replaced it is on OUR side —
    #: a Slack-sourced post is pinned to the Announcements channel. See
    #: `ANNOUNCEMENTS_SLUG` in main.py.
    slack_bot_token: str = ""

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
    #: Kokoro voice, named <lang><gender>_<name>; the first letter also selects the
    #: G2P the pipeline uses (see render/tts.py).
    #:
    #: af_heart is the only voice Kokoro grades A, and it shows — the Hindi packs
    #: (hf_alpha/hf_beta, the nearest thing to Indian English) are graded C and read
    #: English as a second language, which is audible. Warmer A-/B alternates worth
    #: hearing: af_bella, af_sarah, bf_emma (British).
    kokoro_voice: str = "af_heart"
    #: Slightly under 1.0 reads as a person explaining, not a system announcing.
    kokoro_speed: float = 0.95
    #: Hard cap on a single scene's spoken length so one runaway scene cannot
    #: stretch the render; longer scenes are clamped.
    render_scene_max_ms: int = 15000
    #: Background footage library: <mood>.mp4 per broll mood. Shared with the web
    #: app's /broll/<clipId>.mp4 path, hence the default inside public/. A scene
    #: whose mood has no clip here falls back to the CSS gradient.
    broll_dir: str = "../public/broll"

    @property
    def llm_api_key(self) -> str:
        """The gateway key if there is one, otherwise a direct Anthropic key."""
        return self.litellm_api_key or self.anthropic_api_key

    @property
    def supabase_storage_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key and self.supabase_storage_bucket)

    @property
    def dev_auth_enabled(self) -> bool:
        return bool(self.dev_auth_email)


settings = Settings()
