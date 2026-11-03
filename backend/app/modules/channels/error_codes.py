"""WhatsApp Cloud API error codes and how the outbox treats them (design §15 "Outcomes").

Verified against https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes on
``ERROR_TABLE_CHECKED`` for Graph API ``GRAPH_API_VERSION`` (changelog: v26.0 introduced 2026-07-29; v24.0 and
v25.0 remain available until 2028). Re-verify at the next build and bump both constants.

Classes:
- ``retry``: transient; retry with backoff (the row stays ``pending``).
- ``throttle``: rate limit or pacing; retry after the documented wait.
- ``failed``: a validation, permission or recipient error; the row becomes ``failed`` (never retried).
- ``blocked``: a policy state the person must resolve (closed window, paused template, opt-out); ``blocked``.
- ``unknown``: the request may have been processed (timeouts, resets, 5xx); the row becomes ``unknown`` and is
  never resent automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GRAPH_API_VERSION = "v26.0"
ERROR_TABLE_CHECKED = "2026-11-03"

Outcome = Literal["retry", "throttle", "failed", "blocked", "unknown"]


@dataclass(frozen=True)
class ErrorEntry:
    code: int
    title: str
    outcome: Outcome


_ENTRIES: tuple[ErrorEntry, ...] = (
    ErrorEntry(0, "Cannot authenticate user (token)", "failed"),
    ErrorEntry(1, "Invalid request or possible server error", "retry"),
    ErrorEntry(2, "Temporary downtime or overload", "retry"),
    ErrorEntry(3, "Capability or permissions issue", "failed"),
    ErrorEntry(4, "App API rate limit reached", "throttle"),
    ErrorEntry(10, "Permission missing or removed", "failed"),
    ErrorEntry(33, "Phone number deleted or unknown id", "failed"),
    ErrorEntry(100, "Unsupported or misspelled parameter", "failed"),
    ErrorEntry(190, "Access token expired", "failed"),
    ErrorEntry(200, "No access token provided", "failed"),
    ErrorEntry(368, "Account restricted or disabled (policy)", "failed"),
    ErrorEntry(80007, "WABA rate limit reached", "throttle"),
    ErrorEntry(130429, "Message throughput limit reached", "throttle"),
    ErrorEntry(130472, "Recipient in a marketing experiment", "failed"),
    ErrorEntry(130497, "Restricted from messaging this country", "failed"),
    ErrorEntry(130403, "Recipient blocked the business", "failed"),
    ErrorEntry(131000, "Unknown error", "retry"),
    ErrorEntry(131005, "Permission missing or removed", "failed"),
    ErrorEntry(131008, "Missing required parameter", "failed"),
    ErrorEntry(131009, "Invalid parameter value", "failed"),
    ErrorEntry(131016, "Service temporarily unavailable", "retry"),
    ErrorEntry(131021, "Sender and recipient are the same", "failed"),
    ErrorEntry(131026, "Message undeliverable to recipient", "failed"),
    ErrorEntry(131031, "Account restricted or data verification failed", "failed"),
    ErrorEntry(131037, "Display name not approved", "failed"),
    ErrorEntry(131042, "Payment method error", "failed"),
    ErrorEntry(131045, "Phone number registration error", "failed"),
    ErrorEntry(131047, "24-hour customer service window closed", "blocked"),
    ErrorEntry(131048, "Sending restricted (spam or blocks)", "failed"),
    ErrorEntry(131049, "Withheld to protect engagement", "blocked"),
    ErrorEntry(131050, "Recipient opted out of marketing", "blocked"),
    ErrorEntry(131051, "Unsupported message type", "failed"),
    ErrorEntry(131052, "Cannot download the user's media", "failed"),
    ErrorEntry(131053, "Cannot upload media", "failed"),
    ErrorEntry(131056, "Too many messages to the same recipient", "throttle"),
    ErrorEntry(131057, "Business account in maintenance mode", "throttle"),
    ErrorEntry(131063, "Marketing templates disabled on Cloud API", "blocked"),
    ErrorEntry(131064, "Messaging limit from template classification violations", "blocked"),
    ErrorEntry(132000, "Template parameter count mismatch", "failed"),
    ErrorEntry(132001, "Template missing or not approved", "blocked"),
    ErrorEntry(132005, "Translated text too long", "failed"),
    ErrorEntry(132007, "Template violates policy", "blocked"),
    ErrorEntry(132012, "Template parameter format incorrect", "failed"),
    ErrorEntry(132015, "Template paused for low quality", "blocked"),
    ErrorEntry(132016, "Template permanently disabled", "blocked"),
    ErrorEntry(132018, "Template validation error", "failed"),
    ErrorEntry(132068, "Flow blocked", "failed"),
    ErrorEntry(132069, "Flow throttled", "throttle"),
    ErrorEntry(133000, "Previous deregistration failed", "failed"),
    ErrorEntry(133004, "Server temporarily unavailable", "retry"),
    ErrorEntry(133005, "Two-step PIN incorrect", "failed"),
    ErrorEntry(133006, "Phone number needs verification", "failed"),
    ErrorEntry(133008, "Too many PIN guesses", "throttle"),
    ErrorEntry(133009, "PIN entered too quickly", "throttle"),
    ErrorEntry(133010, "Phone number not registered", "failed"),
    ErrorEntry(133015, "Phone number recently deleted", "throttle"),
    ErrorEntry(133016, "Too many registration attempts", "throttle"),
    ErrorEntry(134011, "Payments terms acceptance pending", "failed"),
    ErrorEntry(135000, "Unknown parameter error", "failed"),
    ErrorEntry(2388019, "Template limit exceeded", "failed"),
    ErrorEntry(2494100, "Account in maintenance mode", "throttle"),
)

ERROR_TABLE: dict[int, ErrorEntry] = {e.code: e for e in _ENTRIES}
#: "not processed" family: retry with backoff (design §15)
NOT_PROCESSED_CODES = frozenset(e.code for e in _ENTRIES if e.outcome in ("retry", "throttle"))


def classify(http_status: int | None, error_code: int | None) -> Outcome:
    """Outcome for a provider response. ``http_status`` None means the request may have reached the provider
    (timeout or reset after sending) and the result is unknown."""
    if http_status is None or http_status >= 500:
        return "unknown"
    if http_status == 429:
        return "throttle"
    if error_code is not None:
        entry = ERROR_TABLE.get(error_code)
        if entry is not None:
            return entry.outcome
        if 200 <= error_code <= 299:
            return "failed"  # permission family
    if 400 <= http_status < 500:
        return "failed"
    return "retry"


def title_of(error_code: int | None) -> str | None:
    if error_code is None:
        return None
    entry = ERROR_TABLE.get(error_code)
    if entry is not None:
        return entry.title
    if 200 <= error_code <= 299:
        return "Permission missing or removed"
    return None


__all__ = ["ERROR_TABLE", "ERROR_TABLE_CHECKED", "GRAPH_API_VERSION", "NOT_PROCESSED_CODES", "ErrorEntry", "Outcome", "classify", "title_of"]
