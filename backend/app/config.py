"""Settings, read from the environment or backend/.env."""

from __future__ import annotations

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

    # --- storage --------------------------------------------------------------
    #: Uploads land here. ponytail: local disk only. Swap for S3 presigned PUT when
    #: more than one box serves the feed.
    media_dir: str = "./.storage"

    @property
    def dev_auth_enabled(self) -> bool:
        return bool(self.dev_auth_email)


settings = Settings()
