"""The canonical fixture world for tasks/briefings tests (fixtures.md §2-§7), built on real PostgreSQL.

Identity, parties and sales belong to lanes that merge later, so this module models their part of the
world behind the same seams the real modules will use:
- ``actor_for_member``: a fake member actor builder from the frozen role templates (catalogue grants);
- SourceReaders for ``sales.quote``, ``sales.customer_message``, ``sales.enquiry``, ``parties.party`` and
  ``identity.membership`` backed by in-memory records;
- the ``sales.quote.review`` approval handler (eligibility per permissions.md §10).
Domain events are emitted with the real outbox at their fixture times exactly as the owning modules
will emit them, proposals are real approvals rows, and the tasks/briefings seeds run unchanged.

Switching to the real world when sales merges: build the company through ``registry.seeds`` instead of
``FakeWorld.build_sales_history`` and drop the fake readers/handler; every test reads ids from
``world.refs`` (fixture keys) and expected text from ``app.seed.world.keys.EXPECTED``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from app.core.clock import FrozenClock
from app.modules.approvals import service as approvals
from app.modules.approvals.service import ApprovalHandler, TargetRef
from app.platform import sources
from app.platform.authz import actors
from app.platform.authz.catalogue import template_grants
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.identity.models import AppUser, Membership
from app.platform.org.models import Branch, Company
from app.platform.org.workcal import WorkCalendar, WorkHoliday, WorkShift
from app.platform.sources import MoneyFact, SourceFacts
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys

IST = ZoneInfo(keys.ZONE)
UTC = ZoneInfo("UTC")
D0 = keys.CLOCK_D0  # Mon 2026-10-12 08:55 IST


def ist(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def d0(hh: int, mm: int = 0) -> datetime:
    return ist(2026, 10, 12, hh, mm)


QUOTE_CLOSED = frozenset({"won", "lost", "cancelled", "archived", "deleted"})
SOURCE_TYPES = ("sales.quote", "sales.customer_message", "sales.enquiry", "parties.party", "identity.membership",
                "identity.user_preference", "ui.recent_record", "search.recent")


@dataclass
class QuoteRec:
    id: uuid.UUID
    number: str
    party: str
    owner: str
    status: str
    amount: str
    currency: str
    created_at: datetime
    valid_until: date | None = None
    sent_at: datetime | None = None
    origin_message: str | None = None
    revision_no: int = 1
    version: int = 1


@dataclass
class MessageRec:
    id: uuid.UUID
    party: str
    contact: str
    assignee: str
    received_at: datetime
    channel: str = "email"
    status: str = "received"
    replied_at: datetime | None = None
    linked_quotes: list[str] = field(default_factory=list)
    version: int = 1


@dataclass
class EnquiryRec:
    id: uuid.UUID
    number: str
    party: str
    owner: str
    received_at: datetime
    channel: str
    status: str = "received"
    version: int = 1


@dataclass
class PartyRec:
    id: uuid.UUID
    number: str
    name: str
    owner: str
    version: int = 1


ROLE_TEMPLATE = {p.key: p.role_template for p in keys.PEOPLE.values()}
CONTACTS = {"NORDHAUS": "Lena Brandt", "MAISON": "Camille Laurent", "BERG": "Erik Lindqvist", "THORNBURY": "Oliver Hart"}


class FakeWorld:
    """Company, people, calendar, fake sales sources and the event history up to D0 08:55."""

    def __init__(self, clock: FrozenClock) -> None:
        self.clock = clock
        self.refs: dict[str, uuid.UUID] = {}
        self.company_id: uuid.UUID = uuid.uuid7()
        self.branch_ho: uuid.UUID = uuid.uuid7()
        self.branch_fac: uuid.UUID = uuid.uuid7()
        self.quotes: dict[str, QuoteRec] = {}
        self.messages: dict[str, MessageRec] = {}
        self.enquiries: dict[str, EnquiryRec] = {}
        self.parties: dict[str, PartyRec] = {}
        #: per-user permission edits applied by the fake actor builder: key -> {perm: Scope | None}
        self.overrides: dict[str, dict[str, Scope | None]] = {}
        #: onboarding completion facts per user key
        self.user_facts: dict[str, dict[str, Any]] = {}
        self.zones: dict[str, str] = {}
        self.approved: list[uuid.UUID] = []
        self.people = [p for p in keys.PEOPLE.values() if p.slice_no == 1]
        self._previous_builder: Any = None
        self._previous_readers: dict[str, Any] = {}

    def clone(self, clock: FrozenClock) -> FakeWorld:
        """A copy with independent fake records (the database part is shared through the snapshot)."""
        import copy

        other = FakeWorld(clock)
        for name in ("refs", "quotes", "messages", "enquiries", "parties", "overrides", "user_facts", "zones", "approved"):
            setattr(other, name, copy.deepcopy(getattr(self, name)))
        other.company_id, other.branch_ho, other.branch_fac = self.company_id, self.branch_ho, self.branch_fac
        return other

    # ---- identity seams -----------------------------------------------------------------------------
    def key_of(self, user_id: uuid.UUID | None) -> str | None:
        for key, value in self.refs.items():
            if value == user_id and key in keys.PEOPLE:
                return key
        return None

    def actor(self, person: str, *, channel: str = "test") -> ActorContext:
        user_id = self.refs[person]
        grants = dict(template_grants()[ROLE_TEMPLATE[person]])
        for perm, scope in self.overrides.get(person, {}).items():
            if scope is None:
                grants.pop(perm, None)
            else:
                grants[perm] = scope
        team = keys.PEOPLE[person].team
        peers = frozenset(self.refs[p.key] for p in self.people if p.team == team and team is not None and p.key in self.refs)
        return ActorContext(
            actor_type="user", company_id=self.company_id, user_id=user_id, display_name=keys.PEOPLE[person].name,
            branch_ids=frozenset({self.branch_ho}), team_peer_user_ids=peers, permissions=MappingProxyType(grants),
            channel=channel,  # type: ignore[arg-type]
            time_zone=self.zones.get(person, keys.ZONE),
        )

    def _builder(self, company_id: uuid.UUID, user_id: uuid.UUID, channel: str) -> ActorContext | None:
        if company_id != self.company_id:
            return None
        person = self.key_of(user_id)
        if person is None:
            return None
        return self.actor(person, channel=channel)

    # ---- source readers ------------------------------------------------------------------------------
    def _party_name(self, key: str) -> str:
        return keys.PARTY_NAMES[key]

    def read_quote(self, _uow: UnitOfWork, source_id: uuid.UUID) -> SourceFacts | None:
        q = next((q for q in self.quotes.values() if q.id == source_id), None)
        if q is None or q.status == "deleted":
            return None
        party = self.parties[q.party]
        valid_end = (
            datetime.combine(q.valid_until + timedelta(days=1), time(0, 0), tzinfo=IST).astimezone(UTC) if q.valid_until else None
        )
        return SourceFacts(
            source_type="sales.quote", source_id=q.id, version=q.version, label=f"{q.number} · {party.name}", status=q.status,
            owner_user_id=self.refs[q.owner], branch_id=self.branch_ho, required_permission="sales.quote.read",
            canonical_path=f"/sales/quotes/{q.id}", is_closed=q.status in QUOTE_CLOSED,
            deadlines={"valid_until_end": valid_end} if valid_end else {},
            facts={
                "quote_number": q.number, "party_name": party.name, "party_id": str(party.id),
                "valid_until": q.valid_until.isoformat() if q.valid_until else None,
                "origin_message_id": str(self.messages[q.origin_message].id) if q.origin_message else None,
                "sent_at": q.sent_at.isoformat() if q.sent_at else None, "created_at": q.created_at.isoformat(),
                "revision_no": q.revision_no,
            },
            money=[MoneyFact(amount=q.amount, currency=q.currency)],
        )

    def read_message(self, _uow: UnitOfWork, source_id: uuid.UUID) -> SourceFacts | None:
        m = next((m for m in self.messages.values() if m.id == source_id), None)
        if m is None:
            return None
        party = self.parties[m.party]
        return SourceFacts(
            source_type="sales.customer_message", source_id=m.id, version=m.version,
            label=f"Message from {m.contact} ({party.name})", status=m.status, owner_user_id=self.refs[m.assignee],
            branch_id=self.branch_ho, required_permission="sales.customer_message.read",
            canonical_path=f"/sales/messages/{m.id}",
            facts={
                "party_id": str(party.id), "party_name": party.name, "contact_name": m.contact, "channel": m.channel,
                "received_at": m.received_at.isoformat(), "replied_at": m.replied_at.isoformat() if m.replied_at else None,
                "linked_quote_ids": [str(self.quotes[k].id) for k in m.linked_quotes],
            },
        )

    def read_enquiry(self, _uow: UnitOfWork, source_id: uuid.UUID) -> SourceFacts | None:
        e = next((e for e in self.enquiries.values() if e.id == source_id), None)
        if e is None:
            return None
        party = self.parties[e.party]
        return SourceFacts(
            source_type="sales.enquiry", source_id=e.id, version=e.version, label=f"{e.number} · {party.name}",
            status=e.status, owner_user_id=self.refs[e.owner], branch_id=self.branch_ho,
            required_permission="sales.enquiry.read", canonical_path=f"/sales/enquiries/{e.id}",
            is_closed=e.status in ("quoted", "closed"),
            facts={"enquiry_number": e.number, "party_name": party.name, "received_at": e.received_at.isoformat(),
                   "channel": e.channel},
        )

    def read_party(self, _uow: UnitOfWork, source_id: uuid.UUID) -> SourceFacts | None:
        p = next((p for p in self.parties.values() if p.id == source_id), None)
        if p is None:
            return None
        return SourceFacts(
            source_type="parties.party", source_id=p.id, version=p.version, label=p.name, status="active",
            owner_user_id=self.refs[p.owner], branch_id=None, required_permission="parties.party.read",
            canonical_path=f"/parties/{p.id}", facts={"name": p.name, "party_number": p.number},
        )

    def read_membership(self, _uow: UnitOfWork, membership_id: uuid.UUID) -> SourceFacts | None:
        person = next((k for k, v in self.refs.items() if v == membership_id and k.endswith("_MEMBERSHIP")), None)
        if person is None:
            return None
        key = person.removesuffix("_MEMBERSHIP")
        return SourceFacts(
            source_type="identity.membership", source_id=membership_id, version=1, label=keys.PEOPLE[key].name,
            status="active", owner_user_id=self.refs[key], branch_id=self.branch_ho, required_permission="identity.user.read",
            canonical_path=f"/settings/users/{self.refs[key]}", facts={"role_templates": [ROLE_TEMPLATE[key]]},
        )

    def _user_reader(self, source_type: str, fact: str) -> Any:
        def read(_uow: UnitOfWork, user_id: uuid.UUID) -> SourceFacts | None:
            person = self.key_of(user_id)
            if person is None:
                return None
            facts = self.user_facts.get(person, {})
            return SourceFacts(
                source_type=source_type, source_id=user_id, version=1, label=source_type, status="active",
                owner_user_id=user_id, branch_id=None, required_permission="org.directory.read", canonical_path="/me",
                facts={fact: facts.get(fact, 0)},
            )

        return read

    def install(self) -> None:
        self._previous_builder = actors._builder
        actors.register_member_actor_builder(self._builder)
        for source_type in SOURCE_TYPES:
            self._previous_readers[source_type] = sources._READERS.get(source_type)
        sources.register_reader("sales.quote", self.read_quote)
        sources.register_reader("sales.customer_message", self.read_message)
        sources.register_reader("sales.enquiry", self.read_enquiry)
        sources.register_reader("parties.party", self.read_party)
        sources.register_reader("identity.membership", self.read_membership)
        sources.register_reader("identity.user_preference", self._user_reader("identity.user_preference", "briefing_saved"))
        sources.register_reader("ui.recent_record", self._user_reader("ui.recent_record", "count"))
        sources.register_reader("search.recent", self._user_reader("search.recent", "count"))
        approvals.register_handler(
            ApprovalHandler(
                kind="sales.quote.review",
                approve_permission="sales.quote.approve",
                current_version=self._quote_version,
                on_approved=lambda _uow, p: self.approved.append(p.id),
                on_rejected=lambda _uow, p: None,
                can_decide=self._can_decide,
            )
        )

    def uninstall(self) -> None:
        actors.register_member_actor_builder(self._previous_builder)
        for source_type, reader in self._previous_readers.items():
            if reader is None:
                sources._READERS.pop(source_type, None)
            else:
                sources._READERS[source_type] = reader
        approvals._HANDLERS.pop("sales.quote.review", None)

    def _quote_version(self, _uow: UnitOfWork, target: TargetRef) -> int | None:
        q = next((q for q in self.quotes.values() if q.id == target.target_id), None)
        return q.version if q is not None and q.status != "deleted" else None

    def _can_decide(self, uow: UnitOfWork, proposal: Any) -> bool:
        """permissions.md §10: sales.quote.approve covering the quote; price overrides also need
        sales.quote_price.approve."""
        from app.modules.tasks.visibility import scope_allows

        exceptions = (proposal.facts or {}).get("exceptions") or []
        if exceptions and not uow.actor.can("sales.quote_price.approve"):
            return False
        for target in approvals.targets_of(uow, proposal):
            facts = self.read_quote(uow, target.target_id)
            if facts is None or not scope_allows(uow.actor, "sales.quote.approve", owner_ids=(facts.owner_user_id,)):
                return False
        return True

    # ---- helpers --------------------------------------------------------------------------------------
    def at(self, when: datetime) -> None:
        self.clock.set(when)

    def drain(self) -> int:
        from app.platform.jobs.worker import drain

        return drain()

    @contextmanager
    def uow(self, person: str | None = None) -> Iterator[UnitOfWork]:
        actor = self.actor(person) if person else ActorContext.system(self.company_id, reason="test")
        with UnitOfWork(actor) as uow:
            yield uow

    def emit(self, person: str | None, name: str, aggregate_id: uuid.UUID, payload: dict[str, Any], *,
             version: int | None = None, agent: bool = False) -> uuid.UUID:
        actor = self.actor(person) if person else ActorContext.system(self.company_id, reason="test")
        if agent:
            actor = actor.with_(actor_type="agent")
        with UnitOfWork(actor) as uow:
            return uow.emit(name, aggregate_id=aggregate_id, payload=payload, aggregate_version=version)

    def emit_quote(self, person: str, name: str, quote_key: str, *, agent: bool = False, **payload: Any) -> uuid.UUID:
        q = self.quotes[quote_key]
        return self.emit(person, name, q.id, {"quote_id": str(q.id), **payload}, version=q.version, agent=agent)

    def submit_review(self, person: str, quote_key: str, exceptions: list[str]) -> uuid.UUID:
        q = self.quotes[quote_key]
        with self.uow(person) as uow:
            proposal = approvals.submit(
                uow, kind="sales.quote.review", targets=[TargetRef("sales.quote", q.id, q.version)],
                content={"quote": q.number, "amount": q.amount, "currency": q.currency, "version": q.version},
                title=f"Review {q.number}", facts={"exceptions": exceptions, "quote_number": q.number},
                expires_in=timedelta(hours=24),
            )
            return proposal.id

    def change_quote(self, quote_key: str, **changes: Any) -> QuoteRec:
        q = self.quotes[quote_key]
        for k, v in changes.items():
            setattr(q, k, v)
        q.version += 1
        return q

    # ---- build ------------------------------------------------------------------------------------------
    def build_company(self) -> None:
        self.at(ist(2026, 6, 1, 9, 0))
        with UnitOfWork(ActorContext.system(None, reason="test-world")) as uow:
            uow.add(Company(id=self.company_id, company_key=f"cd-{self.company_id.hex[:10]}", legal_name=keys.COMPANY_LEGAL_NAME,
                            display_name=keys.COMPANY_DISPLAY_NAME, is_demo=True))
            for person in self.people:
                user_id = uuid.uuid7()
                self.refs[person.key] = user_id
                uow.add(AppUser(id=user_id, email=f"{user_id.hex[:12]}.{person.email}",
                                email_normalized=f"{user_id.hex[:12]}.{person.email}", display_name=person.name,
                                full_name=person.name, status="active"))
        with UnitOfWork(ActorContext.system(self.company_id, reason="test-world")) as uow:
            uow.add(Branch(id=self.branch_ho, company_id=self.company_id, branch_code=keys.BRANCHES.HO, name="Head Office", is_head_office=True))
            uow.add(Branch(id=self.branch_fac, company_id=self.company_id, branch_code=keys.BRANCHES.FAC, name="Factory"))
            uow.flush()
            for person in self.people:
                if person.key == "ARJUN":
                    continue  # activated at D0 08:00
                self._membership(uow, person.key)
            uow.flush()
            for person in self.people:
                if person.manager and person.key != "ARJUN":
                    self._set_manager(uow, person.key)
            cal = WorkCalendar(code=keys.CALENDARS.HO_GEN, name="Head office", time_zone=keys.ZONE, is_default=True)
            uow.add(cal)
            uow.flush()
            uow.add(WorkShift(calendar_id=cal.id, code="GEN", name="General", start_local=time(9, 30), end_local=time(18, 30)))
            uow.add(WorkHoliday(calendar_id=cal.id, holiday_date=date(2026, 10, 22), name="Demo holiday"))
        for n, (key, number) in enumerate((("NORDHAUS", keys.PARTIES.NORDHAUS), ("MAISON", keys.PARTIES.MAISON),
                                           ("BERG", keys.PARTIES.BERG), ("THORNBURY", keys.PARTIES.THORNBURY))):
            owner = "NEHA" if key == "THORNBURY" else "MEERA"
            self.parties[key] = PartyRec(id=uuid.uuid7(), number=number, name=keys.PARTY_NAMES[key], owner=owner)
            self.refs[key] = self.parties[key].id
            del n

    def _membership(self, uow: UnitOfWork, person: str) -> None:
        mid = uuid.uuid7()
        self.refs[f"{person}_MEMBERSHIP"] = mid
        uow.add(Membership(id=mid, company_id=self.company_id, user_id=self.refs[person], status="active",
                           default_branch_id=self.branch_ho, job_title=keys.PEOPLE[person].role_template))

    def _set_manager(self, uow: UnitOfWork, person: str) -> None:
        from sqlalchemy import select

        manager = keys.PEOPLE[person].manager
        if manager is None:
            return
        m = uow.session.scalars(select(Membership).where(Membership.id == self.refs[f"{person}_MEMBERSHIP"])).one()
        m.manager_membership_id = self.refs[f"{manager}_MEMBERSHIP"]

    def _quote(self, key: str, number: str, party: str, owner: str, status: str, amount: str, currency: str,
               created_at: datetime, **extra: Any) -> QuoteRec:
        q = QuoteRec(id=uuid.uuid7(), number=number, party=party, owner=owner, status=status, amount=amount, currency=currency,
                     created_at=created_at, **extra)
        self.quotes[key] = q
        self.refs[key] = q.id
        return q

    def build_sales_history(self) -> None:
        """Quotes, enquiries, messages and proposals of fixtures.md §7 in allocation order and time."""
        q = self._quote
        q("Q_BERG_WON", keys.QUOTES.BERG_WON, "BERG", "MEERA", "won", "5700.00", "EUR", ist(2026, 7, 24, 11))
        q("Q_THORNBURY_LOST", keys.QUOTES.THORNBURY_LOST, "THORNBURY", "NEHA", "lost", "5250.00", "GBP", ist(2026, 8, 3, 11))
        q("PRIOR_WON", keys.QUOTES.PRIOR_WON, "NORDHAUS", "MEERA", "won", "5760.00", "EUR", ist(2026, 8, 13, 11))

        self.at(ist(2026, 9, 8, 10, 0))  # ENQ-2026-0001 (D-34)
        self.enquiries["ENQ_MAISON"] = EnquiryRec(uuid.uuid7(), keys.ENQUIRIES.MAISON, "MAISON", "MEERA", ist(2026, 9, 8, 10), "email")
        self.refs["ENQ_MAISON"] = self.enquiries["ENQ_MAISON"].id
        e = self.enquiries["ENQ_MAISON"]
        self.emit("MEERA", "sales.enquiry.received", e.id, {"enquiry_id": str(e.id), "enquiry_number": e.number,
                  "party_id": str(self.parties["MAISON"].id), "channel": "email", "owner_user_id": str(self.refs["MEERA"])}, version=1)
        self.drain()

        self.at(ist(2026, 9, 9, 11, 0))  # LK-QT-2026-0004
        q4 = q("Q_THORNBURY_EXPIRING", keys.QUOTES.THORNBURY_EXPIRING, "THORNBURY", "NEHA", "draft", "5880.00", "GBP", ist(2026, 9, 9, 11))
        self.emit_quote("NEHA", "sales.quote.created", "Q_THORNBURY_EXPIRING", quote_number=q4.number,
                        owner_user_id=str(self.refs["NEHA"]), party_id=str(self.parties["THORNBURY"].id))
        self.drain()

        self.at(ist(2026, 9, 10, 12, 0))  # LK-QT-2026-0005 from ENQ-2026-0001
        q5 = q("Q_MAISON_OVERRIDE", keys.QUOTES.MAISON_OVERRIDE, "MAISON", "MEERA", "draft", "5280.00", "EUR", ist(2026, 9, 10, 12))
        self.emit_quote("MEERA", "sales.quote.created", "Q_MAISON_OVERRIDE", quote_number=q5.number,
                        owner_user_id=str(self.refs["MEERA"]), party_id=str(self.parties["MAISON"].id), enquiry_id=str(e.id))
        e.status, e.version = "quoted", e.version + 1
        self.emit("MEERA", "sales.enquiry.quoted", e.id, {"enquiry_id": str(e.id), "quote_id": str(q5.id)}, version=e.version)
        self.drain()

        self.at(ist(2026, 9, 11, 11, 0))  # LK-QT-2026-0006
        q6 = q("Q_BERG_EXPIRING", keys.QUOTES.BERG_EXPIRING, "BERG", "MEERA", "draft", "5700.00", "EUR", ist(2026, 9, 11, 11))
        self.emit_quote("MEERA", "sales.quote.created", "Q_BERG_EXPIRING", quote_number=q6.number,
                        owner_user_id=str(self.refs["MEERA"]), party_id=str(self.parties["BERG"].id))
        self.drain()

        for key, person, at in (("Q_THORNBURY_EXPIRING", "NEHA", ist(2026, 9, 12, 9, 30)), ("Q_BERG_EXPIRING", "MEERA", ist(2026, 9, 12, 10, 0))):
            self.at(at)  # sent Sat 2026-09-12, validity 30 days -> valid until 2026-10-12
            self.change_quote(key, status="sent", valid_until=date(2026, 10, 12), sent_at=at)
            rec = self.quotes[key]
            self.emit_quote(person, "sales.quote.issued", key, revision_id=str(uuid.uuid7()), revision_no=1, valid_until="2026-10-12")
            self.emit_quote(person, "sales.quote.status_changed", key, version=rec.version, action="mark_sent",
                            from_status="draft", to_status="sent")
            self.emit_quote(person, "sales.quote.marked_sent", key, revision_id=str(uuid.uuid7()), dispatch_id=str(uuid.uuid7()))
            self.drain()

        self.at(ist(2026, 10, 7, 15, 0))  # ENQ-2026-0002 (D-5), phone
        self.enquiries["ENQ_THORNBURY"] = EnquiryRec(uuid.uuid7(), keys.ENQUIRIES.THORNBURY, "THORNBURY", "NEHA", ist(2026, 10, 7, 15), "phone")
        self.refs["ENQ_THORNBURY"] = self.enquiries["ENQ_THORNBURY"].id
        e2 = self.enquiries["ENQ_THORNBURY"]
        self.emit("NEHA", "sales.enquiry.received", e2.id, {"enquiry_id": str(e2.id), "enquiry_number": e2.number,
                  "party_id": str(self.parties["THORNBURY"].id), "channel": "phone", "owner_user_id": str(self.refs["NEHA"])}, version=1)
        self.drain()

        self.at(ist(2026, 10, 9, 12, 0))  # LK-QT-2026-0007 (D-3) from ENQ-2026-0002
        q7 = q("Q_THORNBURY_OVERRIDE", keys.QUOTES.THORNBURY_OVERRIDE, "THORNBURY", "NEHA", "draft", "5850.00", "GBP", ist(2026, 10, 9, 12))
        self.emit_quote("NEHA", "sales.quote.created", "Q_THORNBURY_OVERRIDE", quote_number=q7.number,
                        owner_user_id=str(self.refs["NEHA"]), party_id=str(self.parties["THORNBURY"].id), enquiry_id=str(e2.id))
        e2.status, e2.version = "quoted", e2.version + 1
        self.emit("NEHA", "sales.enquiry.quoted", e2.id, {"enquiry_id": str(e2.id), "quote_id": str(q7.id)}, version=e2.version)
        self.drain()

        self.at(ist(2026, 10, 11, 10, 5))  # Maison shipping address changed by Priya (D-1 10:05)
        maison = self.parties["MAISON"]
        maison.version += 1
        self.emit("PRIYA", "parties.party.updated", maison.id, {"party_id": str(maison.id), "party_number": maison.number,
                  "changed_fields": ["addresses.shipping"]}, version=maison.version)
        self.drain()

        for key, party, at, linked in (("MSG_BERG", "BERG", ist(2026, 10, 11, 17, 40), ["Q_BERG_EXPIRING"]),
                                       ("MSG_NORDHAUS", "NORDHAUS", ist(2026, 10, 11, 19, 20), [])):
            self.at(at)
            m = MessageRec(uuid.uuid7(), party, CONTACTS[party], "MEERA", at, linked_quotes=list(linked))
            self.messages[key] = m
            self.refs[key] = m.id
            self.emit("MEERA", "sales.customer_message.received", m.id, {
                "message_id": str(m.id), "party_id": str(self.parties[party].id), "contact_id": None, "channel": "email",
                "assignee_user_id": str(self.refs["MEERA"]), "enquiry_id": None,
                "quote_id": str(self.quotes[linked[0]].id) if linked else None}, version=m.version)
            self.drain()

    def activate_arjun(self) -> None:
        self.at(d0(8, 0))
        with UnitOfWork(ActorContext.system(self.company_id, reason="test-world")) as uow:
            self._membership(uow, "ARJUN")
            uow.flush()
            self._set_manager(uow, "ARJUN")
        self.emit("PRIYA", "identity.membership.activated", self.refs["ARJUN_MEMBERSHIP"], {
            "membership_id": str(self.refs["ARJUN_MEMBERSHIP"]), "user_id": str(self.refs["ARJUN"]),
            "manager_membership_id": str(self.refs["SAHIL_MEMBERSHIP"])}, version=1)
        self.drain()

    def build_d0_morning(self) -> None:
        self.at(d0(8, 15))  # override set on LK-QT-2026-0005
        self.change_quote("Q_MAISON_OVERRIDE")
        self.emit_quote("MEERA", "sales.quote.updated", "Q_MAISON_OVERRIDE", version=self.quotes["Q_MAISON_OVERRIDE"].version,
                        changed_fields=["lines"], line_change_kinds=["changed"])
        self.drain()
        for key, person, at, exceptions in (("Q_MAISON_OVERRIDE", "MEERA", d0(8, 20), ["price_override"]),
                                            ("Q_THORNBURY_OVERRIDE", "NEHA", d0(8, 30), ["price_override"])):
            self.at(at)
            self._request_review(key, person, exceptions)
        self.at(d0(8, 40))  # Meera's assistant drafts LK-QT-2026-0008 from M1
        q8 = self._quote("Q_NORDHAUS_DRAFT", keys.QUOTES.NORDHAUS_DRAFT, "NORDHAUS", "MEERA", "draft", "5760.00", "EUR", d0(8, 40),
                         origin_message="MSG_NORDHAUS")
        self.emit_quote("MEERA", "sales.quote.created", "Q_NORDHAUS_DRAFT", agent=True, quote_number=q8.number,
                        owner_user_id=str(self.refs["MEERA"]), party_id=str(self.parties["NORDHAUS"].id),
                        origin_message_id=str(self.messages["MSG_NORDHAUS"].id))
        self.drain()
        self.at(d0(8, 45))
        self._request_review("Q_NORDHAUS_DRAFT", "MEERA", [])

    def _request_review(self, key: str, person: str, exceptions: list[str]) -> None:
        q = self.change_quote(key, status="internal_review")
        proposal_id = self.submit_review(person, key, exceptions)
        prop_key = {"Q_MAISON_OVERRIDE": keys.PROPOSALS.MAISON, "Q_THORNBURY_OVERRIDE": keys.PROPOSALS.THORNBURY,
                    "Q_NORDHAUS_DRAFT": keys.PROPOSALS.NORDHAUS}[key]
        self.refs[prop_key] = proposal_id
        self.emit_quote(person, "sales.quote.review_requested", key, proposal_id=str(proposal_id))
        self.emit_quote(person, "sales.quote.status_changed", key, version=q.version, action="submit_review",
                        from_status="draft", to_status="internal_review")
        self.drain()

    def run_seeds(self) -> SeedContext:
        from app.seed.world.briefings import seed_briefings
        from app.seed.world.tasks import seed_tasks

        ctx = SeedContext(company_id=self.company_id, clock=self.clock, refs=self.refs)
        seed_tasks(ctx)
        seed_briefings(ctx)
        return ctx

    def build(self) -> FakeWorld:
        self.install()
        self.build_company()
        self.build_sales_history()
        self.activate_arjun()
        self.build_d0_morning()
        self.run_seeds()
        self.at(D0)
        return self
