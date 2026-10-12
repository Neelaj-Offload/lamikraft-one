"""Application errors rendered as RFC 9457 problem+json with stable snake_case codes."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status: int = 400
    code: str = "bad_request"
    title: str = "Bad request"

    def __init__(self, detail: str | None = None, *, code: str | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if code:
            self.code = code
        self.extra = extra

    def to_problem(self, request_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": f"https://lamikraft.one/problems/{self.code}",
            "title": self.title,
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
        }
        if request_id:
            body["request_id"] = request_id
        if self.extra:
            body.update(self.extra)
        return body


class Unauthenticated(AppError):
    status, code, title = 401, "unauthenticated", "Sign in required"


class Forbidden(AppError):
    status, code, title = 403, "forbidden", "You do not have permission for this action"


class NotFound(AppError):
    status, code, title = 404, "not_found", "Not found"


class Conflict(AppError):
    status, code, title = 409, "conflict", "Conflict"


class VersionConflict(Conflict):
    code, title = "version_conflict", "This record changed since you opened it"


class InvalidTransition(Conflict):
    code, title = "invalid_transition", "That status change is not allowed"


class ValidationFailed(AppError):
    status, code, title = 422, "validation_failed", "Some values are not valid"


class IdempotencyKeyReused(AppError):
    status, code, title = 422, "idempotency_key_reused", "Idempotency key reused with a different request"


class RateLimited(AppError):
    status, code, title = 429, "rate_limited", "Too many attempts; try again later"


class ServiceUnavailable(AppError):
    status, code, title = 503, "service_unavailable", "A required service is not available"


class NotConfigured(AppError):
    status, code, title = 409, "not_configured", "This capability is not configured"


class PermanentJobError(Exception):
    """Raised inside job handlers for failures that must not be retried."""


class RetryableJobError(Exception):
    """Raised inside job handlers for transient failures (retry with backoff)."""
