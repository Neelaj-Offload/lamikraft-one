"""Briefings public service: generation on first open (rollover aware), precompute, event-driven refresh,
immutable versions, acknowledgements, item actions, the delta view, pins and the fallback.

Every briefing is built in a unit of work running as the member (``actor_for_member`` / the request
actor), so only what they may see is ever grouped, counted or phrased. A version is written only when
the visible item set or an item fingerprint changes; time passing alone never creates a version.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select

from app.core.errors import AppError, Forbidden, NotFound, ValidationFailed
from app.core.money import Money
from app.modules.briefings import phrasing as wording
from app.modules.briefings.engine import PRIORITY_RULE_VERSION
from app.modules.briefings.engine import overview as overview_engine
from app.modules.briefings.engine.collect import Collected, Collector
from app.modules.briefings.engine.fingerprint import item_fingerprint, item_set_hash, permission_fingerprint
from app.modules.briefings.engine.labels import due_label, local_iso
from app.modules.briefings.engine.model import Context, Item
from app.modules.briefings.engine.priority import REASON_TEXT
from app.modules.briefings.engine.recommend import render, rule_for
from app.modules.briefings.engine.sections import SECTION_ORDER, SECTION_TITLES, assemble
from app.modules.briefings.errors import ItemChanged, PinEnded
from app.modules.briefings.models import (
    Acknowledgement,
    Briefing,
    BriefingItem,
    BriefingStatus,
    BriefingTrigger,
    BriefingVersion,
    ChangeKind,
    ItemState,
    Pin,
    PinState,
    Recommendation,
    RecommendationStatus,
    SummaryPush,
    VersionCause,
    VersionText,
)
from app.modules.briefings.schemas import (
    AckView,
    ActionView,
    BriefingView,
    DeltaChange,
    DeltaGroup,
    DeltaView,
    ExplainView,
    FallbackView,
    ItemActionRequest,
    ItemActionResult,
    ItemDetailView,
    ItemStateView,
    ItemView,
    LastSuccessfulView,
    NarrationSegment,
    NarrationView,
    OverviewView,
    PersonRef,
    PinCreate,
    PinResolution,
    PinUpdate,
    PinView,
    RecommendationView,
    SectionView,
    SourceRefView,
    SummaryStateView,
)
from app.modules.tasks import responsibility
from app.modules.tasks import service as tasks
from app.modules.tasks.visibility import SourceCache, can_view_source, view_as
from app.platform.authz.context import ActorContext
from app.platform.org.workcal import CalendarView
from app.platform.uow import UnitOfWork

log = structlog.get_logger(__name__)

HORIZON_WORKDAYS = 3
INITIAL_ITEM_CAP = 5
CHANGE_WINDOW = timedelta(days=7)
PIN_IDLE = timedelta(minutes=30)
SNOOZABLE_SECTIONS = frozenset({"needs_you_now", "plan_for_today", "coming_next"})
LOCK_NAMESPACE = "briefings.generate"
#: a version whose phrasing fell back to the template because the provider was down is phrased again on a later
#: open, at most this often
REPHRASE_AFTER = timedelta(minutes=5)
PHRASE_JOB = "briefings.phrase_version"


# ---- calendar context -------------------------------------------------------------------------------
def build_context(cal: CalendarView, work_date: date) -> Context:
    start, end = cal.window(work_date)
    next_day = cal.next_working_day(work_date, 1)
    next_start, next_end = cal.window(next_day)
    _, horizon_end = cal.window(cal.next_working_day(work_date, HORIZON_WORKDAYS))
    return Context(
        work_date=work_date, day_type=cal.day_type(work_date), window_start=start, window_end=end,
        next_window_start=next_start, next_window_end=next_end, horizon_end=horizon_end, initial_cap=INITIAL_ITEM_CAP,
    )


def _user(uow: UnitOfWork) -> uuid.UUID:
    if uow.actor.user_id is None or uow.actor.is_system:
        raise Forbidden(code="person_required")
    uow.actor.require("briefings.briefing.read")
    return uow.actor.user_id


def _lock(uow: UnitOfWork, user_id: uuid.UUID) -> None:
    uow.advisory_xact_lock(LOCK_NAMESPACE, f"{uow.actor.company_id}:{user_id}")


def _briefing(uow: UnitOfWork, user_id: uuid.UUID, work_date: date, *, fresh: bool = False) -> Briefing | None:
    """The member's briefing row. ``fresh`` re-reads the committed state into an already-loaded object
    (needed after taking the per-user lock: another worker may have written a version meanwhile)."""
    stmt = select(Briefing).where(
        Briefing.company_id == uow.actor.company_id, Briefing.user_id == user_id, Briefing.work_date == work_date
    )
    if fresh:
        stmt = stmt.execution_options(populate_existing=True)
    return uow.session.scalars(stmt).first()


def _verified_fp(briefing: Briefing, latest: BriefingVersion | None) -> str | None:
    """The permission fingerprint the latest version's content is known to be right for."""
    return briefing.permission_fingerprint or (latest.permission_fingerprint if latest is not None else None)


def _version(uow: UnitOfWork, briefing_id: uuid.UUID, version: int) -> BriefingVersion | None:
    return uow.session.scalars(
        select(BriefingVersion).where(BriefingVersion.briefing_id == briefing_id, BriefingVersion.version == version)
    ).first()


def _items(uow: UnitOfWork, version_id: uuid.UUID) -> list[BriefingItem]:
    return list(
        uow.session.scalars(select(BriefingItem).where(BriefingItem.version_id == version_id).order_by(BriefingItem.display_ordinal))
    )


# ---- acknowledgement cutoff ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AckState:
    briefing_id: uuid.UUID
    version: int
    method: str
    channel: str
    acknowledged_at: datetime
    data_as_of: datetime


def last_ack(uow: UnitOfWork, user_id: uuid.UUID) -> AckState | None:
    row = uow.session.execute(
        select(Acknowledgement, BriefingVersion.data_as_of)
        .join(BriefingVersion, (BriefingVersion.briefing_id == Acknowledgement.briefing_id) & (BriefingVersion.version == Acknowledgement.version))
        .where(Acknowledgement.company_id == uow.actor.company_id, Acknowledgement.user_id == user_id)
        .order_by(Acknowledgement.acknowledged_at.desc(), Acknowledgement.version.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    ack, data_as_of = row
    return AckState(ack.briefing_id, ack.version, ack.method, ack.channel, ack.acknowledged_at, data_as_of)


def change_cutoff(uow: UnitOfWork, user_id: uuid.UUID, ctx: Context) -> tuple[datetime, bool]:
    """(cutoff, new_member): after the last acknowledged version; for new members their activation;
    never more than seven days before the work window."""
    floor = ctx.window_start - CHANGE_WINDOW
    ack = last_ack(uow, user_id)
    activation = tasks.activation_time(uow, user_id)
    points = [floor] + [p for p in (ack.data_as_of if ack else None, activation) if p is not None]
    new_member = ack is None and activation is not None and activation >= floor
    return max(points), new_member


# ---- build --------------------------------------------------------------------------------------------
@dataclass
class Build:
    items: list[Item]
    sections: list[tuple[str, tuple[uuid.UUID, ...]]]
    initial: list[uuid.UUID]
    overview: dict[str, Any]
    cutoff: datetime
    perm_fp: str
    hash: str
    collected: Collected
    partial: list[dict[str, Any]] = dataclasses.field(default_factory=list)


def build(uow: UnitOfWork, user_id: uuid.UUID, work_date: date, cal: CalendarView) -> Build:
    """Collect as the member, filter, prioritise, place and rank (no writes)."""
    ctx = build_context(cal, work_date)
    cutoff, new_member = change_cutoff(uow, user_id, ctx)
    collected = Collector(uow, user_id, ctx, cal.time_zone).collect(cutoff)
    partial = tasks.partial_families(uow)
    if partial:  # a dead-lettered rule delivery: items of that family may be incomplete (PARTIAL_RULES)
        families = {p["family"] for p in partial}
        collected.candidates = [
            dataclasses.replace(c, uncertainty_flags=tuple(dict.fromkeys((*c.uncertainty_flags, "PARTIAL_RULES"))))
            if c.family in families else c
            for c in collected.candidates
        ]
    assembly = assemble(collected.candidates, ctx)
    facts = overview_engine.count_facts(assembly, ctx)
    name = responsibility.display_names(uow, [user_id]).get(user_id, "")
    template_code, sentence = overview_engine.compose(facts, first_name=responsibility.first_name(name), new_member=new_member)
    stored: dict[str, Any] = {k: v for k, v in facts.items() if v}
    if template_code == "decisions":  # fixtures 9.2: the second clause ("The rest is moving.") is a fact too
        stored["rest_moving"] = facts.get("overdue", 0) == 0
    overview = {
        "sentence": sentence,
        "template_code": template_code,
        "template_version": overview_engine.TEMPLATE_VERSION,
        "facts": stored,
    }
    items = list(assembly.items)
    return Build(
        items=items, sections=list(assembly.sections), initial=list(assembly.initial_issue_ids), overview=overview,
        cutoff=cutoff, perm_fp=permission_fingerprint(uow.actor), hash=item_set_hash(items, overview), collected=collected,
        partial=partial,
    )


def _latest_version(uow: UnitOfWork, briefing: Briefing) -> BriefingVersion | None:
    if briefing.current_version < 1:
        return None
    return _version(uow, briefing.id, briefing.current_version)


def _sync_recommendation(uow: UnitOfWork, user_id: uuid.UUID, item: Item, issue_last_event: uuid.UUID | None) -> dict[str, Any] | None:
    rule = rule_for(item.candidate)
    if rule is None:
        return None
    c = item.candidate
    active = uow.session.scalars(
        select(Recommendation).where(
            Recommendation.company_id == uow.actor.company_id, Recommendation.user_id == user_id,
            Recommendation.issue_id == c.issue_id, Recommendation.status == RecommendationStatus.ACTIVE.value,
        ).with_for_update()
    ).first()
    if active is not None and active.based_on_fingerprint == c.issue_fingerprint and active.action_code == rule.action_code:
        rec = active
    else:
        now = uow.now()
        if active is not None:
            active.status = RecommendationStatus.STALE.value
            active.invalidated_at = now
            active.invalidated_by_event_id = issue_last_event
            uow.flush()
            uow.emit(
                "briefings.recommendation.invalidated",
                aggregate_id=active.id,
                payload={"recommendation_id": str(active.id), "issue_id": str(c.issue_id),
                         "cause_event_id": str(issue_last_event) if issue_last_event else None},
            )
        rec = Recommendation(
            company_id=uow.actor.company_id, user_id=user_id, issue_id=c.issue_id, action_code=rule.action_code,
            reason_code=rule.reason_code, effect_code=rule.effect_code, facts=dict(c.facts), alternatives=list(rule.alternatives),
            based_on_fingerprint=c.issue_fingerprint, status=RecommendationStatus.ACTIVE.value, created_at=now,
        )
        uow.add(rec)
        uow.flush()
    return {"id": str(rec.id), **render(rule, c.facts, set(rule.alternatives))}


def write_version(
    uow: UnitOfWork,
    briefing: Briefing,
    result: Build,
    *,
    cause: str,
    cause_event_ids: list[str] | None = None,
) -> BriefingVersion | None:
    """Persist ``result`` as version n+1 unless nothing visible changed (no manufactured versions).

    The permission fingerprint alone never forces a version: when a permission change leaves the visible
    item set identical, the briefing row records that the latest version was re-verified for it."""
    previous = _latest_version(uow, briefing)
    if previous is not None and previous.item_set_hash == result.hash:
        briefing.permission_fingerprint = result.perm_fp
        briefing.consecutive_failures = 0
        briefing.last_error_code = None
        uow.flush()
        return None
    previous_fps: dict[uuid.UUID, str] = {}
    if previous is not None:
        previous_fps = {i.issue_id: i.fingerprint for i in _items(uow, previous.id)}
    now = uow.now()
    number = briefing.current_version + 1
    version = BriefingVersion(
        company_id=briefing.company_id, briefing_id=briefing.id, version=number, cause=cause,
        cause_event_ids=list(cause_event_ids or []), generated_at=now, data_as_of=now, cutoff_at=result.cutoff,
        permission_fingerprint=result.perm_fp, priority_rule_version=PRIORITY_RULE_VERSION, overview=result.overview,
        sections=[{"code": code, "issue_ids": [str(i) for i in ids]} for code, ids in result.sections],
        initial_issue_ids=[str(i) for i in result.initial], item_set_hash=result.hash,
        partial_families=[dict(p) for p in result.partial],
    )
    uow.add(version)
    uow.flush()
    user_id = briefing.user_id
    issues = result.collected.issues
    for item in result.items:
        c = item.candidate
        fp = item_fingerprint(item)
        if c.issue_id not in previous_fps:
            change_kind = ChangeKind.NEW.value if previous is not None else ChangeKind.UNCHANGED.value
        else:
            change_kind = ChangeKind.UNCHANGED.value if previous_fps[c.issue_id] == fp else ChangeKind.CHANGED.value
        issue = issues.get(c.issue_id)
        recommendation = _sync_recommendation(uow, user_id, item, issue.last_event_id if issue else None)
        uow.add(
            BriefingItem(
                company_id=briefing.company_id, briefing_id=briefing.id, version_id=version.id, issue_id=c.issue_id,
                section=item.section, display_ordinal=item.ordinal, band=item.band, score=item.score,
                reason_codes=list(item.reason_codes), kind=c.kind, family=c.family, title=c.title[:300], summary=c.summary[:600],
                facts=_stored_facts(c.facts, c.money), source_refs=[dict(r) for r in c.source_refs], fact_at=c.fact_at,
                owner_user_id=c.owner_user_id, assignee_user_id=c.assignee_user_id, due_at=c.due_at, due_kind=c.due_kind,
                task_ids=[str(t) for t in c.task_ids], recommendation=recommendation,
                uncertainty_flags=list(c.uncertainty_flags), allowed_actions=[], proposal_ref=c.proposal_ref,
                blocked_by=[dict(b) for b in c.blocked_by], member_count=len(c.members), members=[dict(m) for m in c.members],
                fingerprint=fp, issue_fingerprint=c.issue_fingerprint, change_kind=change_kind,
                changed_since_last_visit=c.changed_since_last_visit, is_reminder=c.category == "reminder",
            )
        )
    briefing.current_version = number
    briefing.last_success_version = number
    briefing.status = BriefingStatus.READY.value
    briefing.generated_at = now
    briefing.last_error_code = None
    briefing.consecutive_failures = 0
    briefing.permission_fingerprint = result.perm_fp
    uow.flush()
    if cause == VersionCause.PERMISSION_CHANGE.value:
        _end_live_pins(uow, briefing)  # a pinned list was read under the old permissions
    enqueue_phrasing(uow, briefing, version)
    if number == 1:
        uow.emit(
            "briefings.briefing.generated", aggregate_id=briefing.id, aggregate_version=number,
            payload={"briefing_id": str(briefing.id), "user_id": str(user_id), "work_date": briefing.work_date.isoformat(),
                     "version": number, "trigger": briefing.trigger},
        )
    else:
        uow.emit(
            "briefings.briefing.updated", aggregate_id=briefing.id, aggregate_version=number,
            payload={"briefing_id": str(briefing.id), "version": number, "cause": cause},
        )
    return version


def enqueue_phrasing(uow: UnitOfWork, briefing: Briefing, version: BriefingVersion, *, retry: str | None = None) -> None:
    """Phrase the version in the background (design §6 step 15): the response always carries the deterministic
    text first. A version precomputed before the shift is phrased through the provider's batch path."""
    batch = briefing.trigger == BriefingTrigger.PRECOMPUTE.value and version.version == 1 and retry is None
    uow.enqueue(
        PHRASE_JOB,
        {"user_id": str(briefing.user_id), "briefing_id": str(briefing.id), "version": version.version,
         "mode": "batch" if batch else "now"},
        dedupe_key=f"brf-phrase:{version.id}" + (f":{retry}" if retry else ""),
        resource_type="briefings.briefing", resource_id=briefing.id,
    )


def _maybe_rephrase(uow: UnitOfWork, briefing: Briefing, version: BriefingVersion, text: VersionText | None) -> None:
    """After an outage the template stands in; a later open (at most every five minutes) tries the model again."""
    if text is None or not wording.outage_only(text):
        return
    now = uow.now()
    if now - text.updated_at < REPHRASE_AFTER:
        return
    enqueue_phrasing(uow, briefing, version, retry=now.strftime("%Y%m%d%H%M"))


def _stored_facts(facts: dict[str, Any], money: tuple[dict[str, str], ...]) -> dict[str, Any]:
    out = dict(facts)
    if money:
        out["_money"] = [{"amount": m["amount"], "currency": m["currency"]} for m in money]
    return out


def _new_briefing(uow: UnitOfWork, user_id: uuid.UUID, work_date: date, cal: CalendarView, trigger: str) -> Briefing:
    briefing = Briefing(
        company_id=uow.actor.company_id, user_id=user_id, work_date=work_date, day_type=cal.day_type(work_date),
        time_zone=cal.time_zone, status=BriefingStatus.GENERATING.value, trigger=trigger,
    )
    uow.add(briefing)
    uow.flush()
    return briefing


def _generate_guarded(
    uow: UnitOfWork, briefing: Briefing, cal: CalendarView, *, cause: str, cause_event_ids: list[str] | None = None
) -> tuple[BriefingVersion | None, str | None]:
    """Generate inside a savepoint: an engine fault leaves no partial rows and is reported, not raised."""
    try:
        with uow.session.begin_nested():
            result = build(uow, briefing.user_id, briefing.work_date, cal)
            version = write_version(uow, briefing, result, cause=cause, cause_event_ids=cause_event_ids)
        return version, None
    except AppError as exc:
        if isinstance(exc, Forbidden | NotFound):
            raise
        return None, _fail(uow, briefing, exc)
    except Exception as exc:  # an engine fault must never take the user's day away
        return None, _fail(uow, briefing, exc)


def _fail(uow: UnitOfWork, briefing: Briefing, exc: BaseException) -> str:
    code = "engine_error"
    log.warning("briefings.generation_failed", briefing_id=str(briefing.id), error=type(exc).__name__)
    if briefing.current_version == 0:
        briefing.status = BriefingStatus.FAILED.value
    briefing.last_error_code = code
    briefing.last_error_at = uow.now()
    briefing.consecutive_failures = (briefing.consecutive_failures or 0) + 1
    uow.flush()
    uow.emit("briefings.briefing.generation_failed", aggregate_id=briefing.id,
             payload={"briefing_id": str(briefing.id), "error_code": code})
    return code


def ensure_briefing(
    uow: UnitOfWork, user_id: uuid.UUID, work_date: date, cal: CalendarView, *, trigger: str
) -> tuple[Briefing, str | None]:
    """The member's briefing for ``work_date``: created once (advisory lock), regenerated when their
    permissions changed. Returns (briefing, error_code-if-generation-failed)."""
    current_fp = permission_fingerprint(uow.actor)
    briefing = _briefing(uow, user_id, work_date)
    if briefing is not None and briefing.status == BriefingStatus.READY.value:
        latest = _latest_version(uow, briefing)
        if latest is not None and _verified_fp(briefing, latest) == current_fp:
            return briefing, None
    _lock(uow, user_id)
    briefing = _briefing(uow, user_id, work_date, fresh=True)
    if briefing is None:
        briefing = _new_briefing(uow, user_id, work_date, cal, trigger)
        _, error = _generate_guarded(uow, briefing, cal, cause=VersionCause.INITIAL.value)
        return briefing, error
    latest = _latest_version(uow, briefing)
    if latest is None:
        _, error = _generate_guarded(uow, briefing, cal, cause=VersionCause.INITIAL.value)
        return briefing, error
    if _verified_fp(briefing, latest) != current_fp:
        _, error = _generate_guarded(uow, briefing, cal, cause=VersionCause.PERMISSION_CHANGE.value)
        return briefing, error
    return briefing, None


# ---- views ---------------------------------------------------------------------------------------------
@dataclass
class _Overlay:
    snoozes: dict[uuid.UUID, Any]
    states: dict[uuid.UUID, ItemState]
    tasks: dict[uuid.UUID, Any]
    issue_states: dict[uuid.UUID, str]
    names: dict[uuid.UUID, str]


def _overlay(uow: UnitOfWork, user_id: uuid.UUID, rows: list[BriefingItem]) -> _Overlay:
    task_ids = {uuid.UUID(t) for r in rows for t in (r.task_ids or [])}
    task_map = tasks.tasks_by_id(uow, task_ids)
    open_for_user = [t for t in task_map.values() if t.is_open]
    issue_ids = {r.issue_id for r in rows} | {uuid.UUID(b["issue_id"]) for r in rows for b in (r.blocked_by or [])}
    issues = tasks.issues_by_id(uow, issue_ids)
    snoozes = tasks.effective_snoozes(uow, user_id, open_for_user, issues)
    states = {
        s.issue_id: s
        for s in uow.session.scalars(
            select(ItemState).where(ItemState.company_id == uow.actor.company_id, ItemState.user_id == user_id,
                                    ItemState.issue_id.in_([r.issue_id for r in rows] or [uuid.UUID(int=0)]))
        )
    }
    names = responsibility.display_names(uow, {r.owner_user_id for r in rows} | {r.assignee_user_id for r in rows})
    return _Overlay(snoozes, states, task_map, {i: v.state for i, v in issues.items()}, names)


def _allowed_actions(uow: UnitOfWork, row: BriefingItem, ov: _Overlay) -> list[ActionView]:
    actions: list[ActionView] = []
    refs = row.source_refs or []
    if refs:
        actions.append(ActionView(action="open", path=refs[0].get("path")))
    if row.is_reminder:
        actions.append(ActionView(action="mark_handled"))
        actions.append(ActionView(action="explain"))
        return actions
    task_infos = [ov.tasks[uuid.UUID(t)] for t in (row.task_ids or []) if uuid.UUID(t) in ov.tasks]
    open_tasks = [t for t in task_infos if t.is_open]
    user_id = uow.actor.user_id
    if row.kind == "approval_decision" and row.proposal_ref and open_tasks:
        pid = uuid.UUID(row.proposal_ref["id"])
        actions.append(ActionView(action="review", path=f"/approvals/{pid}", proposal_id=pid, proposal_version=row.proposal_ref.get("version")))
        if _eligible(uow, pid):
            actions.append(ActionView(action="approve", via="approvals", proposal_id=pid, proposal_version=row.proposal_ref.get("version")))
            actions.append(ActionView(action="reject", via="approvals", requires_reason=True, proposal_id=pid,
                                      proposal_version=row.proposal_ref.get("version")))
    responsible = [t for t in open_tasks if user_id in (t.owner_user_id, t.assignee_user_id)]
    if row.kind != "approval_decision" and any(tasks.can_verify(t) for t in responsible):
        actions.append(ActionView(action="mark_handled"))
    if open_tasks and any(tasks.can_dismiss(uow, t) for t in open_tasks):
        actions.append(ActionView(action="dismiss", requires_reason=True))
    if open_tasks and any(tasks.can_assign(uow, t) for t in open_tasks):
        actions.append(ActionView(action="assign", path=f"/inbox/{open_tasks[0].id}"))
    if open_tasks and row.section in SNOOZABLE_SECTIONS:
        limit = tasks.max_snooze_until(open_tasks, uow.now())
        if limit > uow.now():
            actions.append(ActionView(action="snooze", max_until=limit))
    actions.append(ActionView(action="explain"))
    return actions


def _eligible(uow: UnitOfWork, proposal_id: uuid.UUID) -> bool:
    from app.modules.approvals import service as approvals

    try:
        proposal = approvals.get(uow, proposal_id)
    except NotFound:
        return False
    if proposal.status != "pending" or (proposal.expires_at is not None and proposal.expires_at <= uow.now()):
        return False
    return approvals.is_eligible(uow, proposal)


def _person(user_id: uuid.UUID | None, names: dict[uuid.UUID, str]) -> PersonRef | None:
    if user_id is None:
        return None
    return PersonRef(user_id=user_id, name=names.get(user_id, ""))


def _rec_text(row: BriefingItem, texts: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """(sentence, source) for the item's recommendation: validated phrasing, else the template sentence."""
    entry = (texts or {}).get(str(row.issue_id))
    if entry and entry.get("source") == "model" and entry.get("text"):
        return str(entry["text"]), "llm"
    request = wording.recommendation_request(row)
    if request is None:
        return None, None
    from app.modules.agents.phrasing import render_template

    return overview_engine.sentence_case(render_template(request)), "template"


def _item_view(uow: UnitOfWork, row: BriefingItem, ov: _Overlay, *, zone: str, work_date: date, ctx: Context | None,
               texts: dict[str, Any] | None = None) -> ItemView:
    state = ov.states.get(row.issue_id)
    task_states = {t: ov.tasks[uuid.UUID(t)].state for t in (row.task_ids or []) if uuid.UUID(t) in ov.tasks}
    snooze = ov.snoozes.get(row.issue_id)
    overdue = False
    if row.due_at is not None and ctx is not None and not row.is_reminder and row.section in ("needs_you_now", "plan_for_today", "coming_next"):
        overdue = "OVERDUE" in row.reason_codes or "SOFT_OVERDUE" in row.reason_codes
    blocked_now = None
    if row.blocked_by:
        blocked_now = any(ov.issue_states.get(uuid.UUID(b["issue_id"])) == "open" for b in row.blocked_by)
    money = [Money(amount=m["amount"], currency=m["currency"]) for m in (row.facts or {}).get("_money", [])]
    facts = {k: v for k, v in (row.facts or {}).items() if k != "_money"}
    actions = _allowed_actions(uow, row, ov)
    rec = dict(row.recommendation) if row.recommendation else None
    if rec is not None:  # permitted alternatives only: filtered by what this member may do now
        names = {a.action for a in actions}
        rec["alternatives"] = [a for a in rec.get("alternatives", []) if a in names]
        rec["text"], rec["text_source"] = _rec_text(row, texts)
    return ItemView(
        issue_id=row.issue_id, ordinal=row.display_ordinal, section=row.section, band=row.band, score=row.score,
        reason_codes=list(row.reason_codes), reasons=[REASON_TEXT.get(r, r) for r in row.reason_codes], kind=row.kind,
        family=row.family, title=row.title, summary=row.summary, facts=facts, money=money,
        source_refs=[SourceRefView(**r) for r in (row.source_refs or [])], fact_at=row.fact_at,
        owner=_person(row.owner_user_id, ov.names), assignee=_person(row.assignee_user_id, ov.names), due_at=row.due_at,
        due_local=local_iso(row.due_at, zone),
        due_label=due_label(row.due_at, zone=zone, work_date=work_date, kind=row.kind, overdue=overdue),
        due_kind=row.due_kind, overdue=overdue,
        recommendation=RecommendationView(**rec) if rec else None,
        uncertainty_flags=list(row.uncertainty_flags), allowed_actions=actions,
        proposal_ref=row.proposal_ref, member_count=row.member_count, members=list(row.members or []),
        fingerprint=row.fingerprint, change_kind=row.change_kind, changed_since_last_visit=row.changed_since_last_visit,
        is_reminder=row.is_reminder, blocked=bool(row.blocked_by), blocked_by=list(row.blocked_by or []),
        state=ItemStateView(
            acknowledged=bool(state and state.acked_fingerprint == row.issue_fingerprint),
            snoozed_until=snooze.snoozed_until if snooze else None,
            handled=bool(task_states) and all(s == "done" for s in task_states.values()),
            dismissed=any(s == "dismissed" for s in task_states.values()),
            task_states=task_states,
            issue_state=ov.issue_states.get(row.issue_id),
            blocked_now=blocked_now,
        ),
    )


def _overview_view(uow: UnitOfWork, version: BriefingVersion, zone: str, user_id: uuid.UUID,
                   text: VersionText | None = None) -> OverviewView:
    name = responsibility.display_names(uow, [user_id]).get(user_id, "")
    data = version.overview or {}
    standard = data.get("sentence", "")
    phrased = (text.overview or {}) if text is not None else {}
    model = phrased.get("source") == "model" and bool(phrased.get("text"))
    return OverviewView(
        greeting=overview_engine.greeting(uow.now(), zone, responsibility.first_name(name)),
        sentence=str(phrased["text"]) if model else standard,
        text_source="llm" if model else "template",
        standard_sentence=standard,
        template_code=data.get("template_code", ""),
        facts={k: v if isinstance(v, bool) else int(v) for k, v in (data.get("facts") or {}).items()},
    )


def _ack_view(uow: UnitOfWork, user_id: uuid.UUID) -> AckView | None:
    ack = last_ack(uow, user_id)
    if ack is None:
        return None
    return AckView(briefing_id=ack.briefing_id, version=ack.version, method=ack.method, channel=ack.channel,
                   acknowledged_at=ack.acknowledged_at)


def _live_pin(uow: UnitOfWork, user_id: uuid.UUID) -> Pin | None:
    pin = uow.session.scalars(
        select(Pin).where(Pin.company_id == uow.actor.company_id, Pin.user_id == user_id,
                          Pin.state.in_((PinState.ACTIVE.value, PinState.PAUSED.value)))
        .order_by(Pin.created_at.desc())
    ).first()
    if pin is None or pin.expires_at <= uow.now():
        return None
    return pin


def _pin_view(pin: Pin, current_version: int) -> PinView:
    return PinView(
        id=pin.id, briefing_id=pin.briefing_id, kind=pin.kind, pinned_version=pin.pinned_version, state=pin.state,
        position=pin.position, ordinal_map=list(pin.ordinal_map), expires_at=pin.expires_at,
        pending_updates=max(0, current_version - pin.pinned_version), version=pin.version,
    )


def version_trusted(uow: UnitOfWork, briefing: Briefing, version: BriefingVersion) -> bool:
    """Whether ``version`` was built (or re-verified) under the caller's current permissions. Anything
    else is an older snapshot whose rows must be re-checked before they are shown (design 6/12)."""
    current = permission_fingerprint(uow.actor)
    if version.permission_fingerprint == current:
        return True
    return version.version == briefing.current_version and briefing.permission_fingerprint == current


def row_visible(uow: UnitOfWork, row: BriefingItem, cache: SourceCache) -> bool:
    """Every source and member of a stored row is still visible to the caller (authoritative check)."""
    refs = [(r.get("type"), r.get("id")) for r in (row.source_refs or [])]
    refs += [(m.get("ref_type"), m.get("ref_id")) for m in (row.members or [])]
    for ref_type, ref_id in refs:
        if not ref_type or not ref_id:
            continue
        if not can_view_source(uow, str(ref_type), uuid.UUID(str(ref_id)), cache=cache):
            return False
    return True


def _visible_rows(uow: UnitOfWork, briefing: Briefing, version: BriefingVersion, rows: list[BriefingItem]) -> tuple[list[BriefingItem], bool]:
    """(rows the caller may still see, trusted). An untrusted version keeps only rows whose every source
    and member passes ``can_view_source`` now; its overview (counts over the old item set) is withheld."""
    if version_trusted(uow, briefing, version):
        return rows, True
    cache = SourceCache()
    return [r for r in rows if row_visible(uow, r, cache)], False


def _redact(view: ItemView) -> ItemView:
    """Blocker titles in an older snapshot were checked under old permissions: name none of them."""
    if view.blocked_by:
        view.blocked_by = [{**b, "label": "Another step"} for b in view.blocked_by]
    return view


def render_version(
    uow: UnitOfWork, briefing: Briefing, version: BriefingVersion, cal: CalendarView, *, pin: Pin | None = None
) -> BriefingView:
    user_id = briefing.user_id
    rows, trusted = _visible_rows(uow, briefing, version, _items(uow, version.id))
    ov = _overlay(uow, user_id, rows)
    ctx = build_context(cal, briefing.work_date)
    text = wording.version_text(uow, version.id)
    texts = (text.item_texts or {}) if text is not None else {}
    visible: list[ItemView] = []
    snoozed: list[ItemView] = []
    for row in rows:
        state = ov.states.get(row.issue_id)
        if (row.section == "changes_since_last_visit" and state is not None and state.acked_fingerprint == row.issue_fingerprint
                and row.kind == "change"):
            continue  # acknowledged and unchanged: never re-alerted
        view = _item_view(uow, row, ov, zone=briefing.time_zone, work_date=briefing.work_date, ctx=ctx, texts=texts)
        if not trusted:
            view = _redact(view)
        if row.issue_id in ov.snoozes and pin is None:
            snoozed.append(view)
            continue
        visible.append(view)
    sections = [
        SectionView(code=code, title=SECTION_TITLES[code], total=len(ids), issue_ids=ids)
        for code in SECTION_ORDER
        if (ids := [v.issue_id for v in visible if v.section == code])
    ]
    ack = _ack_view(uow, user_id)
    latest = briefing.current_version
    shown = version.version
    return BriefingView(
        briefing_id=briefing.id, work_date=briefing.work_date, day_type=briefing.day_type, time_zone=briefing.time_zone,
        status="ready", fallback=False,
        ai_status=text.ai_status if text is not None and trusted else "not_used",  # type: ignore[arg-type]
        version=shown, latest_version=latest, generated_at=version.generated_at,
        data_as_of=version.data_as_of, trigger=briefing.trigger, first_opened_at=briefing.first_opened_at,
        overview=_overview_view(uow, version, briefing.time_zone, user_id, text) if trusted else None, sections=sections,
        items=visible,
        initial_view=[v.issue_id for v in visible[:INITIAL_ITEM_CAP]], snoozed=snoozed,
        updates_available=max(0, latest - shown),
        up_to_date=ack is not None and ack.briefing_id == briefing.id and ack.version >= latest,
        last_ack=ack, pin=_pin_view(pin, latest) if pin is not None else None,
        whatsapp_summary=summary_state(uow, user_id, briefing.work_date),
    )


def summary_state(uow: UnitOfWork, user_id: uuid.UUID, work_date: date) -> SummaryStateView | None:
    row = uow.session.scalars(
        select(SummaryPush).where(SummaryPush.company_id == uow.actor.company_id, SummaryPush.user_id == user_id,
                                  SummaryPush.work_date == work_date)
    ).first()
    if row is None:
        return None
    return SummaryStateView(outcome=row.outcome, reason=row.reason, kind=row.kind, version=row.version,  # type: ignore[arg-type]
                            simulated=row.simulated, at=row.created_at, acknowledged_at=row.acknowledged_at,
                            ack_channel=row.ack_channel)


def _fallback_view(uow: UnitOfWork, briefing: Briefing | None, user_id: uuid.UUID, cal: CalendarView, work_date: date,
                   error_code: str) -> BriefingView:
    tasks_list = tasks.list_my_open_tasks(uow)
    last = _last_successful(uow, user_id, cal)
    return BriefingView(
        briefing_id=briefing.id if briefing else None, work_date=work_date, day_type=cal.day_type(work_date),
        time_zone=cal.time_zone, status="fallback", fallback=True, version=None, latest_version=briefing.current_version or None if briefing else None,
        generated_at=None, data_as_of=None, trigger=briefing.trigger if briefing else None,
        first_opened_at=briefing.first_opened_at if briefing else None, overview=None, sections=[], items=[], initial_view=[],
        snoozed=[], updates_available=0, up_to_date=False, last_ack=_ack_view(uow, user_id), pin=None,
        fallback_detail=FallbackView(error_code=error_code, failed_at=uow.now(), tasks=tasks_list, last_successful=last),
    )


def _last_successful(uow: UnitOfWork, user_id: uuid.UUID, cal: CalendarView) -> LastSuccessfulView | None:
    """The most recent ready version on any work date, re-filtered by current permissions."""
    row = uow.session.execute(
        select(Briefing, BriefingVersion)
        .join(BriefingVersion, (BriefingVersion.briefing_id == Briefing.id) & (BriefingVersion.version == Briefing.last_success_version))
        .where(Briefing.company_id == uow.actor.company_id, Briefing.user_id == user_id, Briefing.last_success_version.is_not(None))
        .order_by(BriefingVersion.generated_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    briefing, version = row
    kept, same_permissions = _visible_rows(uow, briefing, version, _items(uow, version.id))
    ov = _overlay(uow, user_id, kept)
    return LastSuccessfulView(
        briefing_id=briefing.id, work_date=briefing.work_date, version=version.version, generated_at=version.generated_at,
        data_as_of=version.data_as_of,
        overview=_overview_view(uow, version, briefing.time_zone, user_id) if same_permissions else None,
        items=[
            v if same_permissions else _redact(v)
            for v in (_item_view(uow, r, ov, zone=briefing.time_zone, work_date=briefing.work_date, ctx=None) for r in kept)
        ],
    )


# ---- today ----------------------------------------------------------------------------------------------
def get_today(uow: UnitOfWork, *, version: int | None = None) -> BriefingView:
    """The member's briefing for the current work date: generated on first open (rollover aware)."""
    user_id = _user(uow)
    cal = responsibility.user_calendar(uow, user_id)
    now = uow.now()
    work_date = cal.work_date(now)
    briefing, error = ensure_briefing(uow, user_id, work_date, cal, trigger=BriefingTrigger.FIRST_OPEN.value)
    if briefing.first_opened_at is None:
        briefing.first_opened_at = now
    if error is not None or briefing.current_version == 0:
        uow.flush()
        return _fallback_view(uow, briefing, user_id, cal, work_date, error or "engine_error")
    pin = _live_pin(uow, user_id)
    if pin is not None and pin.briefing_id == briefing.id:
        shown = _version(uow, briefing.id, pin.pinned_version)
    elif version is not None:
        shown = _version(uow, briefing.id, version)
        if shown is None:
            raise NotFound(code="not_found", resource_type="briefings.version")
        pin = None
    else:
        shown = _latest_version(uow, briefing)
        briefing.served_version = max(briefing.served_version, briefing.current_version)
        pin = None
    uow.flush()
    assert shown is not None
    if shown.version == briefing.current_version:
        _maybe_rephrase(uow, briefing, shown, wording.version_text(uow, shown.id))
    return render_version(uow, briefing, shown, cal, pin=pin)


def today_view_for(uow: UnitOfWork, *, trigger: str) -> BriefingView:
    """The member's latest briefing for another channel (the WhatsApp summary): generated if needed, but not an
    open on the web (``first_opened_at`` and the served version are left alone)."""
    user_id = _user(uow)
    cal = responsibility.user_calendar(uow, user_id)
    work_date = cal.work_date(uow.now())
    briefing, error = ensure_briefing(uow, user_id, work_date, cal, trigger=trigger)
    if error is not None or briefing.current_version == 0:
        return _fallback_view(uow, briefing, user_id, cal, work_date, error or "engine_error")
    latest = _latest_version(uow, briefing)
    assert latest is not None
    return render_version(uow, briefing, latest, cal)


def precompute_for(uow: UnitOfWork, user_id: uuid.UUID, cal: CalendarView, work_date: date) -> bool:
    """Generate ahead of the shift (idempotent: one briefing per user and work date)."""
    if _briefing(uow, user_id, work_date) is not None:
        return False
    briefing, _error = ensure_briefing(uow, user_id, work_date, cal, trigger=BriefingTrigger.PRECOMPUTE.value)
    return briefing.current_version > 0


def generate_as_of(uow: UnitOfWork, *, trigger: str = BriefingTrigger.SEED.value) -> Briefing:
    """Generate the member's briefing for the current clock (fixture seeding and agents)."""
    user_id = _user(uow)
    cal = responsibility.user_calendar(uow, user_id)
    briefing, error = ensure_briefing(uow, user_id, cal.work_date(uow.now()), cal, trigger=trigger)
    if error is not None:
        raise RuntimeError(f"briefing generation failed: {error}")
    if briefing.first_opened_at is None and trigger != BriefingTrigger.PRECOMPUTE.value:
        briefing.first_opened_at = uow.now()
    return briefing


def refresh_member(uow: UnitOfWork, user_id: uuid.UUID, *, cause: str, cause_event_ids: list[str]) -> BriefingVersion | None:
    """Event-driven refresh of a member's current briefing (only if one exists for today)."""
    actor = responsibility.member_actor(uow, user_id)
    if actor is None:
        return None
    member_uow = view_as(uow, actor)
    cal = responsibility.user_calendar(member_uow, user_id)
    work_date = cal.work_date(member_uow.now())
    if _briefing(member_uow, user_id, work_date) is None:
        return None  # their first open computes everything fresh
    _lock(member_uow, user_id)
    # re-read under the lock: a concurrent refresh may have written a version since the first read
    briefing = _briefing(member_uow, user_id, work_date, fresh=True)
    if briefing is None or briefing.status != BriefingStatus.READY.value:
        return None
    latest = _latest_version(member_uow, briefing)
    if latest is not None and _verified_fp(briefing, latest) != permission_fingerprint(actor):
        cause = VersionCause.PERMISSION_CHANGE.value
    version, _error = _generate_guarded(member_uow, briefing, cal, cause=cause, cause_event_ids=cause_event_ids)
    return version


# ---- acknowledgements -------------------------------------------------------------------------------------
def acknowledge(uow: UnitOfWork, briefing_id: uuid.UUID, *, version: int, method: str = "explicit",
                channel_message_id: str | None = None) -> AckView:
    """Monotonic per user: acknowledging an older version than the latest acknowledged one is ignored."""
    user_id = _user(uow)
    briefing = uow.session.scalars(
        select(Briefing).where(Briefing.id == briefing_id, Briefing.company_id == uow.actor.company_id, Briefing.user_id == user_id)
        .with_for_update()
    ).first()
    if briefing is None:
        raise NotFound(code="not_found", resource_type="briefings.briefing")
    target = _version(uow, briefing.id, version)
    if target is None:
        raise NotFound(code="not_found", resource_type="briefings.version")
    if channel_message_id:
        replay = uow.session.scalars(
            select(Acknowledgement).where(Acknowledgement.company_id == uow.actor.company_id, Acknowledgement.user_id == user_id,
                                          Acknowledgement.channel_message_id == channel_message_id)
        ).first()
        if replay is not None:
            return AckView(briefing_id=replay.briefing_id, version=replay.version, method=replay.method,
                           channel=replay.channel, acknowledged_at=replay.acknowledged_at, accepted=False)
    current = last_ack(uow, user_id)
    if current is not None and (current.data_as_of > target.data_as_of or
                                (current.briefing_id == briefing.id and current.version >= version)):
        return AckView(briefing_id=current.briefing_id, version=current.version, method=current.method,
                       channel=current.channel, acknowledged_at=current.acknowledged_at, accepted=False)
    now = uow.now()
    channel = uow.actor.channel if uow.actor.channel in ("web", "voice", "whatsapp", "api") else "web"
    uow.add(Acknowledgement(company_id=uow.actor.company_id, user_id=user_id, briefing_id=briefing.id, version=version,
                            method=method, channel=channel, channel_message_id=channel_message_id, acknowledged_at=now))
    for row in _items(uow, target.id):
        state = uow.session.scalars(
            select(ItemState).where(ItemState.company_id == uow.actor.company_id, ItemState.user_id == user_id,
                                    ItemState.issue_id == row.issue_id).with_for_update()
        ).first()
        if state is None:
            uow.add(ItemState(company_id=uow.actor.company_id, user_id=user_id, issue_id=row.issue_id,
                              acked_fingerprint=row.issue_fingerprint, acked_version_id=target.id, acked_at=now, updated_at=now))
        else:
            state.acked_fingerprint = row.issue_fingerprint
            state.acked_version_id = target.id
            state.acked_at = now
            state.updated_at = now
    uow.flush()
    uow.emit("briefings.briefing.acknowledged", aggregate_id=briefing.id, aggregate_version=version,
             payload={"briefing_id": str(briefing.id), "version": version, "method": method, "channel": channel})
    from app.modules.briefings import summary

    summary.mark_acknowledged(uow, user_id, briefing.id, version, channel=channel)  # any channel: the summary is read
    return AckView(briefing_id=briefing.id, version=version, method=method, channel=channel, acknowledged_at=now)


# ---- item actions --------------------------------------------------------------------------------------------
def _current_item(uow: UnitOfWork, user_id: uuid.UUID, issue_id: uuid.UUID) -> tuple[Briefing, BriefingItem]:
    """The issue as it appears in the member's current briefing (any version of today); else 404."""
    cal = responsibility.user_calendar(uow, user_id)
    briefing = _briefing(uow, user_id, cal.work_date(uow.now()))
    if briefing is None:
        raise NotFound(code="not_found", resource_type="briefings.item")
    found = uow.session.execute(
        select(BriefingItem, BriefingVersion)
        .join(BriefingVersion, BriefingVersion.id == BriefingItem.version_id)
        .where(BriefingItem.briefing_id == briefing.id, BriefingItem.issue_id == issue_id)
        .order_by(BriefingVersion.version.desc())
        .limit(1)
    ).first()
    if found is None:
        raise NotFound(code="not_found", resource_type="briefings.item")
    row, version = found
    if not version_trusted(uow, briefing, version) and not row_visible(uow, row, SourceCache()):
        raise NotFound(code="not_found", resource_type="briefings.item")  # no longer visible: same as never seen
    return briefing, row


def _explain(uow: UnitOfWork, briefing: Briefing, row: BriefingItem) -> ExplainView:
    from app.modules.briefings.engine.priority import WEIGHTS

    reasons = [{"code": r, "text": REASON_TEXT.get(r, r), "points": WEIGHTS.get(r, 0)} for r in row.reason_codes]
    parts = [f"{r['text']} ({r['points']:+d})" for r in reasons]
    text = f"{row.band} priority, score {row.score}: " + "; ".join(parts) + "." if parts else f"{row.band} priority."
    rec = RecommendationView(**row.recommendation) if row.recommendation else None
    if rec is not None:
        text += f" Suggested: {rec.label}. {rec.reason} {rec.effect}".rstrip()
    return ExplainView(
        issue_id=row.issue_id, band=row.band, score=row.score, rule_version=PRIORITY_RULE_VERSION, reasons=reasons,
        recommendation=rec, sources=[SourceRefView(**r) for r in (row.source_refs or [])], text=text,
    )


def _set_state(uow: UnitOfWork, user_id: uuid.UUID, issue_id: uuid.UUID, **fields: Any) -> None:
    state = uow.session.scalars(
        select(ItemState).where(ItemState.company_id == uow.actor.company_id, ItemState.user_id == user_id,
                                ItemState.issue_id == issue_id).with_for_update()
    ).first()
    now = uow.now()
    if state is None:
        state = ItemState(company_id=uow.actor.company_id, user_id=user_id, issue_id=issue_id, updated_at=now)
        uow.add(state)
    for key, value in fields.items():
        setattr(state, key, value)
    state.updated_at = now
    uow.flush()


def run_item_action(uow: UnitOfWork, issue_id: uuid.UUID, body: ItemActionRequest) -> ItemActionResult:
    user_id = _user(uow)
    briefing, row = _current_item(uow, user_id, issue_id)
    if body.item_fingerprint is not None and body.item_fingerprint != row.fingerprint:
        cal = responsibility.user_calendar(uow, user_id)
        ov = _overlay(uow, user_id, [row])
        fresh = _item_view(uow, row, ov, zone=briefing.time_zone, work_date=briefing.work_date,
                           ctx=build_context(cal, briefing.work_date))
        raise ItemChanged(current=fresh.model_dump(mode="json"))
    if body.action == "explain":
        return ItemActionResult(action="explain", issue_id=issue_id, outcome="explained", explanation=_explain(uow, briefing, row))
    if row.is_reminder:
        reminder = tasks.reminder_for_issue_id(uow, user_id, issue_id)
        if reminder is None:
            raise NotFound(code="not_found", resource_type="tasks.reminder")
        if body.action != "mark_handled":
            raise ValidationFailed("Reminders can only be marked done", code="action_not_applicable")
        tasks.complete_reminder(uow, reminder.id)
        _set_state(uow, user_id, issue_id, handled_at=uow.now())
        return ItemActionResult(action="mark_handled", issue_id=issue_id, outcome="completed")
    if body.action == "snooze":
        if body.until is None:
            raise ValidationFailed("Snooze needs an until time", code="until_required")
        out = tasks.snooze_issue(uow, issue_id, body.until, channel=uow.actor.channel)
        uow.emit("briefings.item.snoozed", aggregate_id=issue_id,
                 payload={"issue_id": str(issue_id), "user_id": str(user_id), "snoozed_until": body.until.isoformat()})
        return ItemActionResult(action="snooze", issue_id=issue_id, outcome="snoozed", snoozed_until=out.snoozed_until,
                                max_until=out.max_until)
    if body.action == "unsnooze":
        tasks.unsnooze_issue(uow, issue_id)
        uow.emit("briefings.item.unsnoozed", aggregate_id=issue_id,
                 payload={"issue_id": str(issue_id), "user_id": str(user_id), "snoozed_until": None})
        return ItemActionResult(action="unsnooze", issue_id=issue_id, outcome="unsnoozed")
    if body.action == "mark_handled":
        result = tasks.mark_issue_handled(uow, issue_id, reason_code=body.reason_code, note=body.note)
    elif body.action == "dismiss":
        if body.reason_code is None:
            raise ValidationFailed("A dismissal needs a reason", code="reason_required")
        result = tasks.dismiss_issue(uow, issue_id, reason_code=body.reason_code, note=body.note)
    else:  # pragma: no cover - guarded by the schema
        raise ValidationFailed("unknown action", code="invalid_action")
    now = uow.now()
    if result.outcome == "completed":
        _set_state(uow, user_id, issue_id, handled_at=now, handled_task_ids=[str(t) for t in result.task_ids])
    else:
        _set_state(uow, user_id, issue_id, dismissed_at=now, dismissal_reason_code=body.reason_code)
    return ItemActionResult(action=body.action, issue_id=issue_id, outcome=result.outcome, task_ids=list(result.task_ids))


# ---- delta ----------------------------------------------------------------------------------------------------
def _since_instant(uow: UnitOfWork, user_id: uuid.UUID, since: str, cal: CalendarView) -> datetime:
    work_date = cal.work_date(uow.now())
    if since == "yesterday":
        return cal.window(work_date - timedelta(days=1))[0]
    if since == "last_workday":
        day = work_date - timedelta(days=1)
        for _ in range(30):
            if cal.day_type(day) == "working":
                break
            day -= timedelta(days=1)
        return cal.window(day)[0]
    if since == "last_ack":
        ack = last_ack(uow, user_id)
        return ack.data_as_of if ack else cal.window(work_date)[0] - CHANGE_WINDOW
    try:
        parsed = datetime.fromisoformat(since)
    except ValueError as exc:
        raise ValidationFailed("since must be last_ack, yesterday, last_workday or an ISO timestamp", code="invalid_since") from exc
    if parsed.tzinfo is None:
        raise ValidationFailed("since needs a time zone", code="naive_datetime")
    return parsed


DELTA_MAX_LIMIT = 200


def _delta_cursor(fact_at: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps([fact_at.isoformat(), str(row_id)])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _parse_delta_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        at, rid = json.loads(base64.urlsafe_b64decode((cursor + "=" * (-len(cursor) % 4)).encode()).decode())
        return datetime.fromisoformat(at), uuid.UUID(rid)
    except Exception as exc:  # noqa: BLE001 - malformed client input
        raise ValidationFailed("invalid cursor", code="invalid_cursor") from exc


def get_delta(uow: UnitOfWork, *, since: str = "yesterday", limit: int = 100, cursor: str | None = None) -> DeltaView:
    """Source-linked changes since an instant (permission-filtered; grouped by issue).

    The instant is clamped to the change window (seven days before today's work window), and the
    change-log rows are served as keyset pages over (fact_at, id) (api-conventions 9)."""
    user_id = _user(uow)
    limit = max(1, min(limit, DELTA_MAX_LIMIT))
    cal = responsibility.user_calendar(uow, user_id)
    now = uow.now()
    floor = cal.window(cal.work_date(now))[0] - CHANGE_WINDOW
    instant = max(_since_instant(uow, user_id, since, cal), floor)
    rows = tasks.changes_for(uow, user_id, instant, until=now)
    if cursor:
        after = _parse_delta_cursor(cursor)
        rows = [r for r in rows if (r.fact_at, str(r.id)) > (after[0], str(after[1]))]
    rows.sort(key=lambda r: (r.fact_at, str(r.id)))
    cache = SourceCache()
    page: list[Any] = []
    more = False
    for r in rows:
        if not can_view_source(uow, r.ref_type, r.ref_id, cache=cache):
            continue
        if len(page) == limit:
            more = True
            break
        page.append(r)
    rows = page
    next_cursor = _delta_cursor(rows[-1].fact_at, rows[-1].id) if more and rows else None
    issues = tasks.issues_by_id(uow, {r.issue_id for r in rows})
    names = responsibility.display_names(uow, {r.actor_user_id for r in rows})
    groups: dict[uuid.UUID, DeltaGroup] = {}
    for r in rows:
        issue = issues.get(r.issue_id)
        if issue is None:
            continue
        facts = cache.read(uow, r.ref_type, r.ref_id)
        source = SourceRefView(type=r.ref_type, id=r.ref_id, version=r.ref_version,
                               label=facts.label if facts else "", path=facts.canonical_path if facts else None)
        group = groups.setdefault(r.issue_id, DeltaGroup(issue_id=r.issue_id, title=issue.title, family=issue.family, changes=[]))
        group.changes.append(DeltaChange(
            fact_at=r.fact_at, change_code=r.change_code, actor=_person(r.actor_user_id, names), before=r.before, after=r.after,
            source=source, event_type=r.event_type,
        ))
    return DeltaView(since=since, since_instant=instant, until_instant=now, groups=list(groups.values()),
                     limit=limit, next_cursor=next_cursor)


# ---- generation failures (read by the tasks rules for the admin obligation) -----------------------------------
@dataclass(frozen=True)
class FailureInfo:
    user_id: uuid.UUID
    work_date: date
    failures: int
    error_code: str | None


def failure_info(uow: UnitOfWork, briefing_id: uuid.UUID) -> FailureInfo | None:
    """Consecutive generation failures of one briefing (0 once it generates again)."""
    briefing = uow.session.scalars(
        select(Briefing).where(Briefing.id == briefing_id, Briefing.company_id == uow.actor.company_id)
    ).first()
    if briefing is None:
        return None
    return FailureInfo(briefing.user_id, briefing.work_date, int(briefing.consecutive_failures or 0), briefing.last_error_code)


# ---- pins --------------------------------------------------------------------------------------------------------
def create_pin(uow: UnitOfWork, briefing_id: uuid.UUID, body: PinCreate) -> PinView:
    user_id = _user(uow)
    briefing = uow.session.scalars(
        select(Briefing).where(Briefing.id == briefing_id, Briefing.company_id == uow.actor.company_id, Briefing.user_id == user_id)
    ).first()
    if briefing is None or briefing.current_version < 1:
        raise NotFound(code="not_found", resource_type="briefings.briefing")
    now = uow.now()
    for live in uow.session.scalars(
        select(Pin).where(Pin.company_id == uow.actor.company_id, Pin.user_id == user_id, Pin.kind == body.kind,
                          Pin.state.in_((PinState.ACTIVE.value, PinState.PAUSED.value))).with_for_update()
    ):
        _end_pin(uow, live, PinState.STOPPED.value if live.expires_at > now else PinState.EXPIRED.value)
    version = _latest_version(uow, briefing)
    assert version is not None
    cal = responsibility.user_calendar(uow, user_id)
    view = render_version(uow, briefing, version, cal)
    chosen = view.items if body.detail == "full" else [v for v in view.items if v.issue_id in set(view.initial_view)]
    ordinal_map = [{"ordinal": n, "issue_id": str(v.issue_id), "display_ordinal": v.ordinal} for n, v in enumerate(chosen, start=1)]
    pin = Pin(company_id=uow.actor.company_id, user_id=user_id, briefing_id=briefing.id, kind=body.kind,
              pinned_version=version.version, ordinal_map=ordinal_map, state=PinState.ACTIVE.value, position=0,
              channel=uow.actor.channel, expires_at=now + PIN_IDLE)
    uow.add(pin)
    uow.flush()
    uow.emit("briefings.pin.started", aggregate_id=pin.id,
             payload={"pin_id": str(pin.id), "briefing_id": str(briefing.id), "kind": pin.kind})
    return _pin_view(pin, briefing.current_version)


def _end_pin(uow: UnitOfWork, pin: Pin, state: str) -> None:
    pin.state = state
    pin.ended_at = uow.now()
    uow.flush()
    uow.emit("briefings.pin.ended", aggregate_id=pin.id,
             payload={"pin_id": str(pin.id), "briefing_id": str(pin.briefing_id), "kind": pin.kind})


def _end_live_pins(uow: UnitOfWork, briefing: Briefing) -> None:
    for pin in uow.session.scalars(
        select(Pin).where(Pin.company_id == briefing.company_id, Pin.briefing_id == briefing.id,
                          Pin.state.in_((PinState.ACTIVE.value, PinState.PAUSED.value)))
        .order_by(Pin.id).with_for_update()
    ):
        _end_pin(uow, pin, PinState.STOPPED.value)


def _own_pin(uow: UnitOfWork, pin_id: uuid.UUID) -> Pin:
    user_id = _user(uow)
    pin = uow.session.scalars(
        select(Pin).where(Pin.id == pin_id, Pin.company_id == uow.actor.company_id, Pin.user_id == user_id).with_for_update()
    ).first()
    if pin is None:
        raise NotFound(code="not_found", resource_type="briefings.pin")
    if pin.state in (PinState.ACTIVE.value, PinState.PAUSED.value) and pin.expires_at <= uow.now():
        _end_pin(uow, pin, PinState.EXPIRED.value)
    if pin.state not in (PinState.ACTIVE.value, PinState.PAUSED.value):
        raise PinEnded()
    return pin


def update_pin(uow: UnitOfWork, pin_id: uuid.UUID, body: PinUpdate) -> PinView:
    pin = _own_pin(uow, pin_id)
    uow.expect_version(pin, body.expected_version)
    briefing = uow.session.get(Briefing, pin.briefing_id)
    assert briefing is not None
    if body.position is not None:
        pin.position = body.position
    pin.expires_at = uow.now() + PIN_IDLE
    if body.state in ("active", "paused"):
        pin.state = body.state
    uow.flush()
    if body.state == "completed":
        _end_pin(uow, pin, PinState.COMPLETED.value)
        acknowledge(uow, briefing.id, version=pin.pinned_version, method="voice")
    elif body.state == "stopped":
        _end_pin(uow, pin, PinState.STOPPED.value)
    return _pin_view(pin, briefing.current_version)


def resolve_pin(uow: UnitOfWork, pin_id: uuid.UUID, ordinal: int) -> PinResolution:
    pin = _own_pin(uow, pin_id)
    entry = next((e for e in pin.ordinal_map if int(e["ordinal"]) == ordinal), None)
    if entry is None:
        raise NotFound(code="not_found", resource_type="briefings.pin_ordinal")
    pin.expires_at = uow.now() + PIN_IDLE
    issue_id = uuid.UUID(entry["issue_id"])
    briefing = uow.session.get(Briefing, pin.briefing_id)
    assert briefing is not None
    version = _version(uow, briefing.id, pin.pinned_version)
    assert version is not None
    rows, _trusted = _visible_rows(uow, briefing, version, [r for r in _items(uow, version.id) if r.issue_id == issue_id])
    item = None
    resolved = tasks.issue_states(uow, [issue_id]).get(issue_id) == "resolved"
    if rows:
        ov = _overlay(uow, briefing.user_id, rows)
        cal = responsibility.user_calendar(uow, briefing.user_id)
        item = _item_view(uow, rows[0], ov, zone=briefing.time_zone, work_date=briefing.work_date,
                          ctx=build_context(cal, briefing.work_date))
        resolved = resolved or (bool(item.state.task_states) and all(s != "open" and s != "in_progress" for s in item.state.task_states.values()))
    uow.flush()
    return PinResolution(ordinal=ordinal, issue_id=issue_id, resolved_since=resolved, item=item)


# ---- Listen to my day (narration over a voice pin) --------------------------------------------------------------------
def pin_script(uow: UnitOfWork, pin_id: uuid.UUID) -> NarrationView:
    """The narration of a live pin, in the pin's stable order (design §13).

    Each item is a deterministic lead ("Second. Decision.") plus its body: the validated phrasing stored for the
    version when there is one, else the template body built from the same visible facts. Rows the member can no
    longer see are skipped without renumbering the rest (ordinals stay the pin's). Nothing here re-sorts."""
    from app.modules.agents.phrasing import render_template

    pin = _own_pin(uow, pin_id)
    briefing = uow.session.get(Briefing, pin.briefing_id)
    assert briefing is not None
    version = _version(uow, briefing.id, pin.pinned_version)
    assert version is not None
    rows, trusted = _visible_rows(uow, briefing, version, _items(uow, version.id))
    by_issue = {r.issue_id: r for r in rows}
    text = wording.version_text(uow, version.id)
    narration = (text.narration or {}) if text is not None else {}
    segments: list[NarrationSegment] = []
    overview = _overview_view(uow, version, briefing.time_zone, briefing.user_id, text) if trusted else None
    segments.append(NarrationSegment(
        kind="intro", lead=overview.greeting if overview else "Here is your briefing.",
        text=overview.sentence if overview else "", text_source=overview.text_source if overview else "template",
    ))
    spoken = 0
    for entry in pin.ordinal_map:
        row = by_issue.get(uuid.UUID(str(entry["issue_id"])))
        if row is None:
            continue  # no longer visible to the member: never spoken
        stored = narration.get(str(row.issue_id))
        if stored and stored.get("source") == "model" and stored.get("text"):
            body, source = str(stored["text"]), "llm"
        else:
            body = overview_engine.sentence_case(
                render_template(wording.narration_request(row, zone=briefing.time_zone, work_date=briefing.work_date)))
            source = "template"
        ordinal = int(entry["ordinal"])
        refs = row.source_refs or []
        segments.append(NarrationSegment(
            kind="item", ordinal=ordinal, issue_id=row.issue_id,
            lead=f"{wording.ordinal_word(ordinal)}. {wording.family_label(row)}.", text=body, text_source=source,  # type: ignore[arg-type]
            readback=wording.readback_values(row), path=refs[0].get("path") if refs else None,
        ))
        spoken += 1
    more = len(rows) - spoken
    outro = "That is everything for now." if more <= 0 else (
        f"That is the top of your day. {overview_engine.number_word(more).capitalize()} more "
        f"{'item is' if more == 1 else 'items are'} in the full list on Today."
    )
    segments.append(NarrationSegment(kind="outro", lead="", text=outro, text_source="template"))
    uow.flush()
    return NarrationView(
        pin_id=pin.id, briefing_id=briefing.id, pinned_version=pin.pinned_version, language=wording.LANGUAGE,
        ai_status=text.ai_status if text is not None and trusted else "not_used",  # type: ignore[arg-type]
        state=pin.state, position=pin.position, segments=segments,
    )


# ---- one item as a page ---------------------------------------------------------------------------------------------
def get_item(uow: UnitOfWork, issue_id: uuid.UUID) -> ItemDetailView:
    """An item of the member's current briefing with its explanation and evidence (deep-linkable); 404 when the
    issue is not in today's briefing or no longer visible."""
    user_id = _user(uow)
    briefing, row = _current_item(uow, user_id, issue_id)
    version = uow.session.get(BriefingVersion, row.version_id)
    assert version is not None
    cal = responsibility.user_calendar(uow, user_id)
    ov = _overlay(uow, user_id, [row])
    text = wording.version_text(uow, version.id)
    view = _item_view(uow, row, ov, zone=briefing.time_zone, work_date=briefing.work_date, ctx=build_context(cal, briefing.work_date),
                      texts=(text.item_texts or {}) if text is not None else {})
    if not version_trusted(uow, briefing, version):
        view = _redact(view)
    return ItemDetailView(briefing_id=briefing.id, version=version.version, work_date=briefing.work_date, item=view,
                          explanation=_explain(uow, briefing, row))


# ---- UI section ------------------------------------------------------------------------------------------------
def briefing_section(uow: UnitOfWork) -> dict[str, Any]:
    """The bootstrap/poll section: current version and the "N updates" signal (never generates)."""
    actor: ActorContext = uow.actor
    if actor.user_id is None or actor.is_system or not actor.can("briefings.briefing.read"):
        return {}
    cal = responsibility.user_calendar(uow, actor.user_id)
    work_date = cal.work_date(uow.now())
    briefing = _briefing(uow, actor.user_id, work_date)
    if briefing is None:
        return {"status": "not_generated", "work_date": work_date.isoformat(), "version": None, "updates_available": 0}
    acked = uow.session.scalars(
        select(Acknowledgement.version).where(Acknowledgement.briefing_id == briefing.id).order_by(Acknowledgement.version.desc())
    ).first()
    seen = max(briefing.served_version, acked or 0)
    pin = _live_pin(uow, actor.user_id)
    if pin is not None and pin.briefing_id == briefing.id:
        seen = pin.pinned_version
    return {
        "status": briefing.status,
        "briefing_id": str(briefing.id),
        "work_date": work_date.isoformat(),
        "version": briefing.current_version,
        "acknowledged_version": acked,
        "updates_available": max(0, briefing.current_version - seen),
        "generated_at": briefing.generated_at.isoformat() if briefing.generated_at else None,
    }


# ---- refresh audience ----------------------------------------------------------------------------------------
def users_showing_issue(uow: UnitOfWork, issue_id: uuid.UUID) -> set[uuid.UUID]:
    """Users whose latest version on a recent work date contains the issue."""
    cutoff = uow.now().date() - timedelta(days=2)
    rows = uow.session.scalars(
        select(Briefing.user_id)
        .join(BriefingVersion, (BriefingVersion.briefing_id == Briefing.id) & (BriefingVersion.version == Briefing.current_version))
        .join(BriefingItem, BriefingItem.version_id == BriefingVersion.id)
        .where(Briefing.company_id == uow.actor.company_id, Briefing.work_date >= cutoff, BriefingItem.issue_id == issue_id)
    )
    return set(rows)


def request_refresh(uow: UnitOfWork, user_id: uuid.UUID, *, dedupe_key: str) -> bool:
    """Refresh the member's current briefing after a change of their own that has no domain event in the
    catalogue (personal reminders). Members without a briefing around today compute it fresh on first open;
    the refresh still writes a version only when the visible item set changed."""
    if not users_with_current_briefing(uow, {user_id}):
        return False
    uow.enqueue(
        "briefings.refresh_user",
        {"user_id": str(user_id), "cause": VersionCause.EVENT_UPDATE.value},
        dedupe_key=dedupe_key,
        resource_type="identity.user",
        resource_id=user_id,
    )
    return True


def users_with_current_briefing(uow: UnitOfWork, user_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Members (of ``user_ids``) holding a briefing for a work date around today (zones differ by a day
    at most); the refresh job re-checks the member's own current work date."""
    if not user_ids:
        return set()
    today = uow.now().date()
    rows = uow.session.scalars(
        select(Briefing.user_id).where(
            Briefing.company_id == uow.actor.company_id,
            Briefing.user_id.in_(sorted(user_ids)),
            Briefing.work_date >= today - timedelta(days=1),
            Briefing.work_date <= today + timedelta(days=1),
        )
    )
    return set(rows)


def send_summary_now(uow: UnitOfWork) -> SummaryStateView:
    """The member's WhatsApp summary for today, sent on request (idempotent per work date)."""
    from app.modules.briefings import summary

    user_id = _user(uow)
    row = summary.send_summary(uow, user_id)
    state = summary_state(uow, user_id, row.work_date)
    assert state is not None
    return state
