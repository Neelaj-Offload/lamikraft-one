"""Fingerprints: item content, the version's item-set hash and the member's permission fingerprint.

A new version is written only when the item-set hash differs from the latest version (which covers
every item fingerprint, placement and the overview sentence) or the permission fingerprint changed.
"""

from __future__ import annotations

from typing import Any

from app.modules.briefings.engine.model import Item
from app.modules.tasks.issue_keys import fingerprint
from app.platform.authz.context import ActorContext


def item_material(item: Item) -> dict[str, Any]:
    c = item.candidate
    return {
        "issue_id": str(c.issue_id),
        "issue_fingerprint": c.issue_fingerprint,
        "category": c.category,
        "kind": c.kind,
        "section": item.section,
        "band": item.band,
        "score": item.score,
        "reasons": list(item.reason_codes),
        "title": c.title,
        "summary": c.summary,
        "facts": c.facts,
        "money": list(c.money),
        "refs": [[r.get("type"), r.get("id"), r.get("version")] for r in c.source_refs],
        "due_at": c.due_at.isoformat() if c.due_at else None,
        "due_kind": c.due_kind,
        "blocked_by": list(c.blocked_by),
        "changed": c.changed_since_last_visit,
        "members": list(c.members),
        "proposal_ref": c.proposal_ref,
        "flags": list(c.uncertainty_flags),
        "responsibility": c.responsibility,
    }


def item_fingerprint(item: Item) -> str:
    return fingerprint(item_material(item))


def item_set_hash(items: list[Item], overview: dict[str, Any]) -> str:
    return fingerprint(
        {
            "items": [[str(i.issue_id), i.ordinal, item_fingerprint(i)] for i in items],
            "overview": {"sentence": overview.get("sentence"), "facts": overview.get("facts")},
        }
    )


def permission_fingerprint(actor: ActorContext) -> str:
    return fingerprint(
        {
            "user": str(actor.user_id),
            "company": str(actor.company_id),
            "permissions": sorted((k, int(v)) for k, v in actor.permissions.items()),
            "branches": sorted(str(b) for b in actor.branch_ids),
            "team": sorted(str(t) for t in actor.team_peer_user_ids),
            "delegated": sorted((k, sorted(str(u) for u in v)) for k, v in actor.delegated.items()),
        }
    )
