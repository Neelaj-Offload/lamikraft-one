"""Authentication problem codes (api-conventions §3, §7.1). Every sign-in failure uses one generic message."""

from __future__ import annotations

from app.core.errors import AppError, RateLimited, Unauthenticated

GENERIC_SIGN_IN_FAILURE = "The email or password is incorrect, or this account cannot sign in."


class InvalidCredentials(Unauthenticated):
    code, title = "invalid_credentials", "Sign-in failed"

    def __init__(self) -> None:
        super().__init__(GENERIC_SIGN_IN_FAILURE)


class SessionExpired(Unauthenticated):
    code, title = "session_expired", "Your session has ended"

    def __init__(self) -> None:
        super().__init__("Sign in again to continue.")


class LinkInvalidOrUsed(Unauthenticated):
    code, title = "link_invalid_or_used", "This sign-in link is invalid or has been used"

    def __init__(self) -> None:
        super().__init__("Ask for a new sign-in link.")


class TooManyAttempts(RateLimited):
    """429 with ``Retry-After``; ``code`` is ``rate_limited`` or ``account_locked``."""

    def __init__(self, code: str, retry_after_seconds: int) -> None:
        detail = (
            "Too many sign-in attempts. Try again later."
            if code == "rate_limited"
            else "Sign-in is temporarily blocked after repeated failures. Try again later."
        )
        super().__init__(detail, code=code, retry_after_seconds=retry_after_seconds)
        self.retry_after_seconds = retry_after_seconds


class PasswordPolicyViolation(AppError):
    status, code, title = 422, "validation_failed", "The password does not meet the policy"
