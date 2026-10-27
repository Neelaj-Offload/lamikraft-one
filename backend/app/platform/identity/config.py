"""Deployment settings owned by identity (read from ``LK_*`` environment variables and the repository ``.env``).

``LK_TRUSTED_PROXY_HOPS`` — how many reverse proxies in front of the web server **append** the address they saw to
``X-Forwarded-For`` (counted from the right). The same-origin Next.js rewrite does not add or replace that header,
so with the default of 0 nothing in the header is trusted and every request that reaches the API through the local
proxy shares one "address unknown" rate-limit bucket. Production runs behind a reverse proxy (ADR-001) that appends
the client address: set ``LK_TRUSTED_PROXY_HOPS=1`` there. Requested for ``app.core.config.Settings`` (integrator).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import REPO_ROOT


class IdentitySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LK_",
        env_file=(str(REPO_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)


@lru_cache(maxsize=1)
def identity_settings() -> IdentitySettings:
    return IdentitySettings()


def trusted_proxy_hops() -> int:
    return identity_settings().trusted_proxy_hops
