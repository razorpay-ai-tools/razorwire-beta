"""Settings, read from the environment or backend/.env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./razorwire.db"

    # web app origin, for CORS
    web_origin: str = "http://localhost:3000"

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
    #: Uploads land here. ponytail: local disk only. Swap for S3 presigned PUT when
    #: more than one box serves the feed.
    media_dir: str = "./.storage"

    @property
    def dev_auth_enabled(self) -> bool:
        return bool(self.dev_auth_email)


settings = Settings()
