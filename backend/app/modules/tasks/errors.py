"""Task-specific problem codes (api-conventions §3)."""

from __future__ import annotations

from app.core.errors import Conflict, ValidationFailed


class NotComplete(Conflict):
    code, title = "not_complete", "The source shows this is not done yet"


class ActionNotAllowed(Conflict):
    code, title = "action_not_allowed", "This action does not apply here"


class SnoozeBeyondDeadline(ValidationFailed):
    code, title = "snooze_beyond_deadline", "Snoozing cannot move past the deadline"
