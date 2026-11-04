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
    #:
    #: 127.0.0.1 rather than `localhost` for the same reason the web client uses it: the
    #: name resolves to ::1 first, where any wildcard `*:8000` bind on the machine
    #: answers instead of us, so media URLs built on `localhost` 404 in the browser.
    public_base_url: str = "http://127.0.0.1:8000"

    # --- auth -----------------------------------------------------------------
    google_client_id: str = ""
    allowed_hd: str = "razorpay.com"
    #: Local escape hatch. When set and no bearer token is presented, requests are
    #: treated as this user. Leave empty in anything shared.
    dev_auth_email: str = ""
    #: Shared secret required on every API request when set, sent as
    #: `X-Razorwire-Secret`. Exists for one situation: this backend reachable over a
    #: public tunnel with `dev_auth_email` still set, where anyone holding the URL
    #: would otherwise be that user and could spend `litellm_api_key`.
    #:
    #: A spend guard, NOT an identity gate — the web app ships it in a public bundle,
    #: so anyone who can load the frontend can read it. Whatever gates the frontend
    #: (AiSites SSO today) is what decides *who* gets in. Empty disables the check, so
    #: a laptop-only run is unaffected.
    tunnel_secret: str = ""

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
    #: Whatever the gateway routes. `glm-5p3` today; a Claude model here would also work,
    #: since the gateway speaks the same wire format either way.
    llm_model: str = "glm-5p3"

    # --- aidocs ingestion -----------------------------------------------------
    aidocs_server: str = "https://aidocs.razorpay.com"
    #: Service-account key from `aidocs sa key create <sa_id>`.
    #:
    #: Set it anywhere that is not a developer laptop. Unset, `aidocs.py` falls back to
    #: the `aidocs` CLI's own Google session — which does not exist in a container, and
    #: is why the hosted backend answered `api 401 unauthorized` for every document.
    #:
    #: A personal token also works and is the wrong choice: it reads with that person's
    #: permissions and dies when they leave.
    aidocs_token: str = ""

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
    #: Which engine turns the voiced storyboard into an MP4.
    #:
    #:   "ffmpeg"      capture stills with Playwright, join them with xfade. The
    #:                 original path; scenes are cross-faded screenshots.
    #:   "hyperframes" author one HTML composition with a seekable GSAP timeline and
    #:                 render it with the HyperFrames CLI. Elements animate
    #:                 individually, subtitles are their own timed clips, and
    #:                 `hyperframes check` gates layout and WCAG contrast before a
    #:                 single frame is encoded. Needs Node 22+ on PATH.
    #:
    #: Both read the same storyboard and the same measured narration durations, so a
    #: reel rendered either way is timed identically.
    #:
    #: Default is "hyperframes". A box without Node 22+ does not need to set this:
    #: `render_from_voiced` catches the missing toolchain and falls back to ffmpeg,
    #: so the default is safe to ship ahead of the deploy image.
    render_engine: str = "hyperframes"
    #: Post-render QA: EBU R128 loudness normalisation, plus black/silent/frozen
    #: detection logged as warnings. Adds one audio-only ffmpeg pass per render.
    render_qa: bool = True
    #: Optional music bed under the narration, at BED_VOLUME. Empty = narration only.
    render_music_bed: str = ""
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
    #: Backstop against a TTS engine that loops or never terminates — NOT a budget.
    #: The clamp caps the duration we record while the wav keeps its real length, so
    #: a ceiling under the longest legitimate narration silently truncates the voice:
    #: at 15s it was cutting 22% of scenes short, up to 6.3s, and the reel advanced
    #: mid-sentence. Narration is capped at 420 characters (~70 words), which is ~28s
    #: at this voice and speed, so 30s cannot clip real speech. Total length is
    #: governed by MAX_SPOKEN_SECONDS in storyboard.py, which is the actual budget.
    render_scene_max_ms: int = 30000
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
