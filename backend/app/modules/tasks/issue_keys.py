"""Stable issue identity: UUIDv5 of ``company_id|issue_key|occurrence`` (conventions §4).

Issue keys name the root cause deterministically, so regenerations, replays and refreshes always land
on the same id. A resolved issue that recurs opens ``occurrence + 1`` (a new id), so stale
acknowledgements or snoozes never hide a new problem. Grouping follows explicit links only.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

#: Namespace for briefing/task issue ids. Never change: every stored issue id derives from it.
NS_LK_ISSUE = uuid.UUID("0b6f2c1e-7a54-4d3e-9b8a-5c2e1f7d9a63")


def issue_id(company_id: uuid.UUID, issue_key: str, occurrence: int = 1) -> uuid.UUID:
    if occurrence < 1:
        raise ValueError("occurrence starts at 1")
    return uuid.uuid5(NS_LK_ISSUE, f"{company_id}|{issue_key}|{occurrence}")


# ---- key builders (one per root-cause kind) ---------------------------------------------------------
def message_key(message_id: uuid.UUID) -> str:
    return f"msg:{message_id}"


def quote_review_key(quote_id: uuid.UUID) -> str:
    return f"quote:{quote_id}:review"


def quote_expiry_key(quote_id: uuid.UUID) -> str:
    return f"quote:{quote_id}:expiry"


def approval_key(proposal_id: uuid.UUID) -> str:
    return f"approval:{proposal_id}"


def enquiry_key(enquiry_id: uuid.UUID) -> str:
    return f"enquiry:{enquiry_id}"


def party_info_key(party_id: uuid.UUID) -> str:
    return f"info:party:{party_id}"


def onboarding_key(user_id: uuid.UUID, step_key: str) -> str:
    return f"onboarding:{user_id}:{step_key}"


def manual_key(task_id: uuid.UUID) -> str:
    return f"manual:{task_id}"


def reminder_key(reminder_id: uuid.UUID) -> str:
    return f"reminder:{reminder_id}"


def responsibility_key(queue_code: str) -> str:
    return f"responsibility:{queue_code}"


# ---- fingerprints ---------------------------------------------------------------------------------
def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(material: Mapping[str, Any] | list[Any]) -> str:
    """SHA-256 of the canonical JSON of material facts only (versions and timestamps of reads excluded)."""
    return hashlib.sha256(canonical(material).encode()).hexdigest()
