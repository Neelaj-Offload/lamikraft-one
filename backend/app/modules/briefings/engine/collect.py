"""Collection: everything that may enter a member's briefing, read inside a unit of work running as that
member and filtered through visibility before grouping or counting (briefing design §6 steps 5-7).

(a) open obligations where the member is assignee, owner or candidate approver; (c) change-log rows after
the cutoff on issues they watch or are responsible for; (d) closures after the cutoff made by others;
(f) their own private reminders. Every source reference is re-checked with ``can_view_source``; approval
items additionally require current eligibility (``approvals.is_eligible``) on a pending proposal.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.errors import NotFound
from app.modules.briefings.engine.model import Candidate, Context
from app.modules.tasks import issue_keys
from app.modules.tasks import service as tasks
from app.modules.tasks.responsibility import display_names, first_name
from app.modules.tasks.schemas import ChangeInfo, IssueInfo, ReminderInfo, TaskInfo
from app.modules.tasks.visibility import (
    ADMIN_REF_TYPES,
    INTERNAL_REF_TYPES,
    SourceCache,
    can_view_source,
)
from app.platform.uow import UnitOfWork

RESPONSIBILITY_RANK = {"YOUR_DECISION": 0, "ASSIGNED_TO_YOU": 1, "DELEGATED_TO_YOU": 2, "YOU_OWN": 3, "FYI": 4}
CUSTOMER_KINDS = frozenset({"reply_needed", "quote_expiry", "enquiry_reply"})
OVERVIEW_CLASS = {
    "reply_needed": "customer_reply",
    "enquiry_reply": "customer_reply",
    "quote_expiry": "quote_expiry",
    "approval_decision": "decision",
    "onboarding_step": "onboarding_step",
}
_FAR = datetime.max.replace(tzinfo=ZoneInfo("UTC"))


@dataclass
class Collected:
    candidates: list[Candidate]
    #: issue ids whose open obligations were collected (for allowed actions and snooze bounds)
    tasks_by_issue: dict[uuid.UUID, list[TaskInfo]]
    issues: dict[uuid.UUID, IssueInfo]


def _local(value: datetime | None, zone: str) -> str:
    if value is None:
        return ""
    return value.astimezone(ZoneInfo(zone)).strftime("%a %d %b %H:%M")


def _responsibility(t: TaskInfo, user_id: uuid.UUID) -> str:
    if t.kind == "approval_decision" and user_id in t.candidates:
        return "YOUR_DECISION"
    if t.assignee_user_id == user_id:
        return "ASSIGNED_TO_YOU"
    if t.owner_user_id == user_id:
        return "YOU_OWN"
    if user_id in t.candidates:
        return "YOUR_DECISION"
    return "FYI"


class Collector:
    def __init__(self, uow: UnitOfWork, user_id: uuid.UUID, ctx: Context, zone: str) -> None:
        self.uow = uow
        self.user_id = user_id
        self.ctx = ctx
        self.zone = zone
        self.cache = SourceCache()
        self._proposals: dict[uuid.UUID, Any] = {}

    # ---- visibility helpers ---------------------------------------------------------------------
    def visible(self, ref_type: str | None, ref_id: uuid.UUID | None) -> bool:
        if ref_type is None or ref_id is None:
            return True
        if ref_type == "identity.user":
            return True  # onboarding refers to people in the directory (org.directory.read for every member)
        if ref_type == "tasks.task":
            return True  # the task row itself passed the task visibility clause
        if ref_type in ADMIN_REF_TYPES:
            return self.uow.actor.can("tasks.queue.manage")
        return can_view_source(self.uow, ref_type, ref_id, cache=self.cache)

    def proposal(self, proposal_id: uuid.UUID) -> Any | None:
        from app.modules.approvals import service as approvals

        if proposal_id not in self._proposals:
            try:
                self._proposals[proposal_id] = approvals.get(self.uow, proposal_id)
            except NotFound:
                self._proposals[proposal_id] = None
        return self._proposals[proposal_id]

    def task_visible(self, t: TaskInfo, issue: IssueInfo | None) -> bool:
        if not self.visible(t.primary_ref_type, t.primary_ref_id):
            return False
        if issue is not None and not self.visible(issue.root_ref_type, issue.root_ref_id):
            return False
        if t.kind == "approval_decision":
            from app.modules.approvals import service as approvals

            proposal = self.proposal(t.primary_ref_id) if t.primary_ref_id else None
            if proposal is None or proposal.status != "pending":
                return False
            if proposal.expires_at is not None and proposal.expires_at <= self.uow.now():
                return False
            if not approvals.is_eligible(self.uow, proposal):
                return False
        return True

    def source_refs(self, issue: IssueInfo, extra: list[tuple[str | None, uuid.UUID | None]] = ()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """(source_refs, members) — visible ones only; member_count counts visible members."""
        refs: list[dict[str, Any]] = []
        members: list[dict[str, Any]] = []
        seen: set[tuple[str, uuid.UUID]] = set()
        pairs = [(m.ref_type, m.ref_id, m.label, m.role, m.ref_version) for m in issue.members]
        pairs += [(rt, rid, "", "related", None) for rt, rid in extra if rt and rid]
        for ref_type, ref_id, label, role, version in pairs:
            if (ref_type, ref_id) in seen or ref_type in INTERNAL_REF_TYPES:
                continue
            seen.add((ref_type, ref_id))
            if not self.visible(ref_type, ref_id):
                continue
            path = None
            if ref_type == "approvals.proposal":
                path = f"/approvals/{ref_id}"
            else:
                facts = self.cache.read(self.uow, ref_type, ref_id)
                if facts is not None:
                    path = facts.canonical_path
                    label = facts.label or label
                    version = facts.version
            refs.append({"type": ref_type, "id": str(ref_id), "version": version, "label": label, "path": path})
            members.append({"ref_type": ref_type, "ref_id": str(ref_id), "label": label, "role": role})
        return refs, members

    def money_of(self, issue: IssueInfo) -> tuple[dict[str, str], ...]:
        out: list[dict[str, str]] = []
        for m in issue.members:
            if m.ref_type in INTERNAL_REF_TYPES or m.ref_type == "approvals.proposal" or not self.visible(m.ref_type, m.ref_id):
                continue
            facts = self.cache.read(self.uow, m.ref_type, m.ref_id)
            if facts is None:
                continue
            out.extend({"amount": mf.amount, "currency": mf.currency, "source_id": str(m.ref_id)} for mf in facts.money)
        return tuple(out)

    # ---- collection -----------------------------------------------------------------------------
    def collect(self, cutoff: datetime) -> Collected:
        uow = self.uow
        now = uow.now()  # facts recorded after the build instant are not part of this snapshot
        open_tasks = tasks.open_tasks_for(uow, self.user_id, as_of=now)
        changes = tasks.changes_for(uow, self.user_id, cutoff, until=now)
        closed = tasks.closed_tasks_for(uow, self.user_id, cutoff, until=now)
        blockers = {b for t in open_tasks for b in t.blocked_by}
        issues = tasks.issues_by_id(
            uow, {t.issue_id for t in open_tasks} | {c.issue_id for c in changes} | {h.issue_id for h in closed} | blockers
        )
        blocker_tasks: dict[uuid.UUID, list[TaskInfo]] = defaultdict(list)
        for bt in tasks.open_tasks_in(uow, blockers):
            blocker_tasks[bt.issue_id].append(bt)

        by_issue: dict[uuid.UUID, list[TaskInfo]] = defaultdict(list)
        for t in open_tasks:
            if self.task_visible(t, issues.get(t.issue_id)):
                by_issue[t.issue_id].append(t)

        # precedence per issue: open obligation > handled for you > change since the last visit
        handled_by_issue: dict[uuid.UUID, list[TaskInfo]] = defaultdict(list)
        for h in closed:
            if h.issue_id not in by_issue and self.visible(h.primary_ref_type, h.primary_ref_id):
                handled_by_issue[h.issue_id].append(h)
        changes_by_issue: dict[uuid.UUID, list[ChangeInfo]] = defaultdict(list)
        for c in changes:
            if self.visible(c.ref_type, c.ref_id):
                changes_by_issue[c.issue_id].append(c)

        names = display_names(uow, {h.closed_by for h in closed} | {c.actor_user_id for c in changes}
                              | {t.initiator_user_id for ts in by_issue.values() for t in ts})
        candidates: list[Candidate] = []
        for issue_id, issue_tasks in by_issue.items():
            issue = issues.get(issue_id)
            if issue is None:
                continue
            candidates.append(self._obligation(issue, issue_tasks, issues, blocker_tasks, bool(changes_by_issue.get(issue_id)), names))
        for issue_id, rows in handled_by_issue.items():
            issue = issues.get(issue_id)
            if issue is not None:
                candidates.append(self._handled(issue, rows, names))
        for issue_id, rows in changes_by_issue.items():
            if issue_id in by_issue or issue_id in handled_by_issue:
                continue
            issue = issues.get(issue_id)
            if issue is None or not self.visible(issue.root_ref_type, issue.root_ref_id):
                continue
            candidates.append(self._change(issue, rows, names))
        for reminder in tasks.reminders_for(uow, self.user_id, as_of=now):
            candidate = self._reminder(reminder)
            if candidate is not None:
                candidates.append(candidate)
        return Collected(candidates=candidates, tasks_by_issue=dict(by_issue), issues=issues)

    # ---- candidate builders -----------------------------------------------------------------------
    def _obligation(
        self,
        issue: IssueInfo,
        issue_tasks: list[TaskInfo],
        issues: dict[uuid.UUID, IssueInfo],
        blocker_tasks: dict[uuid.UUID, list[TaskInfo]],
        changed: bool,
        names: dict[uuid.UUID, str],
    ) -> Candidate:
        ranked = sorted(
            issue_tasks,
            key=lambda t: (RESPONSIBILITY_RANK[_responsibility(t, self.user_id)], t.due_at or _FAR, t.created_at, str(t.id)),
        )
        primary = ranked[0]
        responsibility = _responsibility(primary, self.user_id)
        blocked_ids = [b for b in primary.blocked_by]
        blocked_by: list[dict[str, Any]] = []
        unblock_today = False
        for b in blocked_ids:
            blocker = issues.get(b)
            if blocker is None:
                continue
            visible = self.visible(blocker.root_ref_type, blocker.root_ref_id)
            blocked_by.append({"issue_id": str(b), "label": blocker.title if visible else "Another step", "state": blocker.state})
            for bt in blocker_tasks.get(b, []):
                if bt.due_at is not None and bt.due_at < self.ctx.window_end:
                    unblock_today = True
        refs, members = self.source_refs(issue, [(primary.primary_ref_type, primary.primary_ref_id)])
        facts = self._facts(issue, primary)
        title, summary = self._texts(issue, primary, facts, bool(blocked_by), names)
        proposal_ref = None
        flags: list[str] = []
        if primary.kind == "approval_decision" and primary.primary_ref_id:
            proposal = self.proposal(primary.primary_ref_id)
            if proposal is not None:
                proposal_ref = {
                    "id": str(proposal.id), "version": proposal.version, "content_hash": proposal.content_hash,
                    "expires_at": proposal.expires_at.isoformat() if proposal.expires_at else None, "status": proposal.status,
                }
                flags.extend(self._approval_flags(proposal))
        money = self.money_of(issue)
        if primary.kind in ("quote_expiry", "review_draft") and not money:
            flags.append("MISSING_PRICE")
        return Candidate(
            issue_id=issue.id,
            category="obligation",
            kind=primary.kind,
            family=issue.family,
            title=title,
            summary=summary,
            fact_at=issue.first_seen_at,
            issue_fingerprint=issue.fingerprint,
            facts=facts,
            money=money,
            source_refs=tuple(refs),
            responsibility=responsibility,  # type: ignore[arg-type]
            owner_user_id=primary.owner_user_id,
            assignee_user_id=primary.assignee_user_id,
            due_at=primary.due_at,
            due_kind=primary.due_kind,
            overdue_fact=primary.overdue_emitted_at is not None,
            blocked=bool(blocked_by),
            blocked_by=tuple(blocked_by),
            unblock_expected_today=unblock_today,
            impact=("CUSTOMER_COMMITMENT_AT_RISK",) if primary.kind in CUSTOMER_KINDS else (),
            actionable=True,
            is_decision=primary.kind == "approval_decision",
            changed_since_last_visit=changed,
            members=tuple(members),
            task_ids=tuple(t.id for t in ranked),
            proposal_ref=proposal_ref,
            uncertainty_flags=tuple(dict.fromkeys(flags)),
            overview_class=OVERVIEW_CLASS.get(primary.kind, "task"),
        )

    def _approval_flags(self, proposal: Any) -> list[str]:
        from app.modules.approvals import service as approvals

        flags: list[str] = []
        for target in approvals.targets_of(self.uow, proposal):
            if target.target_version is None:
                continue
            facts = self.cache.read(self.uow, target.target_type, target.target_id)
            if facts is not None and facts.version is not None and facts.version != target.target_version:
                flags.append("SOURCE_CHANGED_SINCE_REVIEW")
        return flags

    def _facts(self, issue: IssueInfo, primary: TaskInfo) -> dict[str, Any]:
        """Safe display facts from visible members and the task (no restricted values)."""
        facts: dict[str, Any] = {}
        for m in issue.members:
            if m.ref_type in INTERNAL_REF_TYPES or not self.visible(m.ref_type, m.ref_id):
                continue
            for key in ("party_name", "contact_name", "channel", "quote_number", "valid_until", "status", "enquiry_number",
                        "exceptions", "name"):
                if m.facts.get(key) is not None and key not in facts:
                    facts[key] = m.facts[key]
        for key, value in (primary.facts or {}).items():
            if key in ("content_hash", "quote_numbers"):
                continue
            facts.setdefault(key, value)
        if "quote_numbers" in (primary.facts or {}):
            # the rule lists every linked quote; the viewer only learns the numbers of quotes they can open
            facts["quote_numbers"] = [
                str(m.facts["quote_number"]) for m in issue.members
                if m.ref_type == "sales.quote" and m.facts.get("quote_number") and self.visible(m.ref_type, m.ref_id)
            ]
        return facts

    def _texts(self, issue: IssueInfo, t: TaskInfo, facts: dict[str, Any], blocked: bool, names: dict[uuid.UUID, str]) -> tuple[str, str]:
        zone = self.zone
        if t.kind == "reply_needed":
            title = f"Reply to {facts.get('party_name') or issue.title}"
            if blocked:
                numbers = facts.get("quote_numbers") or []
                title += f" — waiting for review of {', '.join(numbers)}" if numbers else " — waiting for a review"
            received = facts.get("received_at")
            when = _local(datetime.fromisoformat(received), zone) if received else ""
            who = facts.get("contact_name") or facts.get("party_name") or "The customer"
            channel = facts.get("channel") or "message"
            return title, f"{who} wrote by {channel} on {when}.".replace(" on .", ".")
        if t.kind == "quote_expiry":
            number = facts.get("quote_number") or issue.title
            if t.due_at is not None and t.due_at < self.ctx.window_start:
                title = f"{number} has expired"
            elif t.due_at is not None and t.due_at <= self.ctx.window_end:
                title = f"{number} expires today"
            else:
                title = f"{number} expires on {facts.get('valid_until')}"
            party = facts.get("party_name")
            return title, f"Sent to {party}; valid until {facts.get('valid_until')}." if party else f"Valid until {facts.get('valid_until')}."
        if t.kind == "approval_decision":
            initiator = first_name(names.get(t.initiator_user_id)) if t.initiator_user_id else ""
            exceptions = facts.get("exceptions") or []
            reason = "a price override" if "price_override" in exceptions else ("an exception" if exceptions else "a review")
            return t.title, f"{initiator or 'A colleague'} requested approval for {reason}."
        if t.kind == "review_draft":
            return t.title, f"Draft for {facts.get('party_name')} is waiting for your review." if facts.get("party_name") else t.title
        return t.title, str((t.facts or {}).get("note") or "")

    def _change(self, issue: IssueInfo, rows: list[ChangeInfo], names: dict[uuid.UUID, str]) -> Candidate:
        latest = rows[-1]
        actor = first_name(names.get(latest.actor_user_id)) if latest.actor_user_id else ""
        title = issue.title + (f" by {actor}" if actor else "")
        refs, members = self.source_refs(issue)
        return Candidate(
            issue_id=issue.id,
            category="change",
            kind="change",
            family=issue.family,
            title=title,
            summary=f"Changed {_local(latest.fact_at, self.zone)}.",
            fact_at=latest.fact_at,
            issue_fingerprint=issue.fingerprint,
            facts={"change_codes": sorted({r.change_code for r in rows}), "changes": len(rows),
                   "event_ids": [str(r.event_id) for r in rows], "after": latest.after or {}},
            source_refs=tuple(refs),
            responsibility="FYI",
            members=tuple(members),
            overview_class=None,
        )

    def _handled(self, issue: IssueInfo, rows: list[TaskInfo], names: dict[uuid.UUID, str]) -> Candidate:
        latest = sorted(rows, key=lambda r: (r.closed_at or _FAR, str(r.id)))[-1]
        closer = first_name(names.get(latest.closed_by)) if latest.closed_by else ""
        evidence = latest.completion_evidence or {}
        decision = evidence.get("decision")
        verb = {"approved": "Approved", "rejected": "Rejected"}.get(str(decision), "Done")
        refs, members = self.source_refs(issue, [(latest.primary_ref_type, latest.primary_ref_id)])
        return Candidate(
            issue_id=issue.id,
            category="handled",
            kind=latest.kind,
            family=issue.family,
            title=latest.title,
            summary=f"{verb} by {closer} {_local(latest.closed_at, self.zone)}.".replace("  ", " "),
            fact_at=latest.closed_at or issue.last_changed_at,
            issue_fingerprint=issue.fingerprint,
            facts={"decision": decision, "closed_by": closer},
            source_refs=tuple(refs),
            responsibility="FYI",
            members=tuple(members),
            task_ids=tuple(r.id for r in rows),
        )

    def _reminder(self, r: ReminderInfo) -> Candidate | None:
        company_id = self.uow.actor.company_id
        assert company_id is not None
        refs: list[dict[str, Any]] = []
        if r.linked_ref_type and r.linked_ref_id and r.linked_ref_type not in INTERNAL_REF_TYPES:
            if self.visible(r.linked_ref_type, r.linked_ref_id):
                facts = self.cache.read(self.uow, r.linked_ref_type, r.linked_ref_id)
                if facts is not None:
                    refs.append({"type": facts.source_type, "id": str(facts.source_id), "version": facts.version,
                                 "label": facts.label, "path": facts.canonical_path})
        return Candidate(
            issue_id=issue_keys.issue_id(company_id, issue_keys.reminder_key(r.id), 1),
            category="reminder",
            kind="reminder",
            family="personal.reminder",
            title=r.text,
            summary="Personal reminder (only you can see this).",
            fact_at=r.created_at,
            issue_fingerprint=issue_keys.fingerprint({"text": r.text, "at": r.remind_at.isoformat(), "state": r.state}),
            facts={"reminder_id": str(r.id), "state": r.state},
            source_refs=tuple(refs),
            responsibility="FYI",
            owner_user_id=r.user_id,
            due_at=r.remind_at,
            due_kind="soft",
            actionable=True,
            overview_class=None,
        )
