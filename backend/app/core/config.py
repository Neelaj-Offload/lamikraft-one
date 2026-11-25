"""Runtime configuration.

All settings come from environment variables (prefix ``LK_``) or the repository-root ``.env``
written by ``lk env init``. Provider secrets keep their vendor-standard names
(``ANTHROPIC_API_KEY``, ``GEMINI_API_KEY``) and are only ever read server-side.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LK_",
        env_file=(str(REPO_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    slot: int = 0

    # --- database -------------------------------------------------------------------------
    pg_host: str = "127.0.0.1"
    pg_port: int = 54329
    db_name: str = "lk_wt0"
    db_owner_user: str = "lk_owner"
    db_owner_password: SecretStr = SecretStr("")
    db_app_user: str = "lk_app"
    db_app_password: SecretStr = SecretStr("")
    pg_superuser: str = "postgres"
    pg_superuser_password: SecretStr = SecretStr("")
    db_pool_size: int = 10

    # --- http -----------------------------------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    web_port: int = 3000
    public_origin: str = "http://127.0.0.1:3000"
    # How many reverse proxies in front of the web server append the address they saw to X-Forwarded-For
    # (counted from the right). 0 trusts nothing in the header: every proxied request shares one
    # "address unknown" rate-limit bucket. Must be 1 behind the production reverse proxy (ADR-001).
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

    # --- secrets --------------------------------------------------------------------------
    secret_key: SecretStr = SecretStr("")
    data_encryption_keys: SecretStr = SecretStr("")  # "kid:base64key,kid2:base64key"

    # --- storage --------------------------------------------------------------------------
    storage_backend: Literal["local_fs", "s3"] = "local_fs"
    storage_dir: Path = BACKEND_DIR / "var" / "storage"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str | None = None
    max_upload_bytes: int = 26_214_400  # 25 MiB

    # --- ai ---------------------------------------------------------------------------------
    ai_mode: Literal["demo", "live"] = "demo"
    model_orchestrator: str = "claude-sonnet-5-5"
    model_escalation: str = "claude-opus-5-5"
    model_phrasing: str = "claude-haiku-5-5"
    model_vision: str = "gemini-3.8-flash"
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("ANTHROPIC_API_KEY", "LK_ANTHROPIC_API_KEY")
    )
    gemini_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("GEMINI_API_KEY", "LK_GEMINI_API_KEY")
    )

    # --- channels ----------------------------------------------------------------------------
    whatsapp_mode: Literal["demo", "live"] = "demo"
    #: Meta WhatsApp Cloud API (live mode needs every value; verified against the Graph API changelog on 2026-11-03)
    whatsapp_phone_number_id: str = ""
    whatsapp_waba_id: str = ""
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")
    #: accepted alongside the current secret while rotating (empty = no previous secret)
    whatsapp_app_secret_previous: SecretStr = SecretStr("")
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_api_version: str = "v26.0"
    #: live mode only sends when this is true (a verified account alone never sends)
    whatsapp_live_outbound: bool = False
    #: development allowlist of E.164 numbers (comma separated); empty = no restriction outside development
    whatsapp_dev_allowlist: str = ""
    email_mode: Literal["demo", "smtp"] = "demo"

    # --- marketplaces (module 5): Amazon Selling Partner API; empty = Demo only ------------------------------
    amazon_lwa_client_id: str = ""
    amazon_lwa_client_secret: SecretStr = SecretStr("")
    amazon_refresh_token: SecretStr = SecretStr("")
    amazon_seller_id: str = ""
    #: India is served by the EU endpoint; the Amazon.in marketplace id
    amazon_endpoint: str = "https://sellingpartnerapi-eu.amazon.com"
    amazon_marketplace_id: str = "A21TJRUUN4KGV"

    # --- behaviour ---------------------------------------------------------------------------
    default_time_zone: str = "Asia/Kolkata"
    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("public_origin")
    @classmethod
    def _no_wildcard_origin(cls, value: str) -> str:
        if "*" in value:
            raise ValueError("LK_PUBLIC_ORIGIN must be an explicit origin, never a wildcard")
        return value.rstrip("/")

    def _url(self, user: str, password: SecretStr, database: str | None = None) -> str:
        from urllib.parse import quote

        return (
            f"postgresql+psycopg://{quote(user)}:{quote(password.get_secret_value())}"
            f"@{self.pg_host}:{self.pg_port}/{database or self.db_name}"
        )

    @property
    def app_database_url(self) -> str:
        return self._url(self.db_app_user, self.db_app_password)

    @property
    def owner_database_url(self) -> str:
        return self._url(self.db_owner_user, self.db_owner_password)

    def superuser_url(self, database: str = "postgres") -> str:
        return self._url(self.pg_superuser, self.pg_superuser_password, database)

    @property
    def is_test(self) -> bool:
        return self.env == "test"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
