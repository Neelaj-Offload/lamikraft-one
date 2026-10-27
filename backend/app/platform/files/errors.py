"""Upload errors (api-conventions §3): 413 ``payload_too_large`` and 415 ``unsupported_media_type``."""

from __future__ import annotations

from app.core.errors import AppError


class PayloadTooLarge(AppError):
    status, code, title = 413, "payload_too_large", "The file is too large"


class UnsupportedMediaType(AppError):
    status, code, title = 415, "unsupported_media_type", "This kind of file is not accepted"
