"""Deployment settings identity reads (``LK_TRUSTED_PROXY_HOPS`` lives in ``app.core.config.Settings``).

``LK_TRUSTED_PROXY_HOPS`` — how many reverse proxies in front of the web server **append** the address they saw to
``X-Forwarded-For`` (counted from the right). The same-origin Next.js rewrite does not add or replace that header,
so with the default of 0 nothing in the header is trusted and every request that reaches the API through the local
proxy shares one "address unknown" rate-limit bucket. Production runs behind a reverse proxy (ADR-001) that appends
the client address: set ``LK_TRUSTED_PROXY_HOPS=1`` there.
"""

from __future__ import annotations

from app.core.config import get_settings


def trusted_proxy_hops() -> int:
    return get_settings().trusted_proxy_hops
