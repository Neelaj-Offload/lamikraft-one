"""The canonical fixture world for tasks/briefings tests (fixtures.md §2-§7), built on real PostgreSQL.

The company is built by the **real** seeds of the installed modules, run in ``(order, name)`` order through
``registry.seeds`` exactly as ``lk seed demo`` does (``app.seed.runner``): identity (10), org (12), parties (20),
catalogue (30), pricing/commercial (40), parties changes (55), identity activation (75), tasks (80) and
briefings (81). Actors come from the real member-actor builder (identity), parties are read by the real
``parties.party`` reader, and permission edits are real override rows that the real builder resolves.

Only what is not merged yet is faked, behind the seams the real modules will use, and only while a fixture
holds the world installed (``install``/``uninstall`` save and restore every registry entry they touch;
nothing is registered at import):
- sales (not merged): SourceReaders for ``sales.quote``, ``sales.customer_message`` and ``sales.enquiry``
  backed by in-memory records, the ``sales.quote.review`` approval handler (eligibility per
  permissions.md §10), and three SeedDefs that emit the sales history at its fixture times (order 50: quotes
  and enquiries up to D-3; order 56: the two customer messages of D-1 evening; order 76: the D0 morning
  reviews and the agent draft). Their records reference the real party ids from the seeded refs.

The identity, ui and search readers (``identity.membership``, ``identity.user_preference``, ``ui.recent_record``,
``search.recent``) are the real modules'; tests that need an onboarding step done record the real fact (a saved
preference, an opened record, a recent search).

Switching to the real world when sales (and the identity readers) merge: delete ``fake_sales_seeds`` and the
build_* history methods, the sales readers/handler (``read_quote``, ``read_message``, ``read_enquiry``,
``_quote_version``, ``_can_decide``) and their entries in ``FAKE_READERS``/``FAKE_HANDLERS``/``install``. Every test reads ids from ``world.refs`` (fixture keys) and expected text from
``app.seed.world.keys.EXPECTED``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.clock import FrozenClock
from app.modules.approvals import service as approvals
from app.modules.approvals.service import ApprovalHandler, TargetRef
from app.platform import sources
from app.platform.authz import actors
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
from app.platform.sources import MoneyFact, SourceFacts
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext, SeedDef
from app.seed.world import keys

IST = ZoneInfo(keys.ZONE)
UTC = ZoneInfo("UTC")
D0 = keys.CLOCK_D0  # Mon 2026-10-12 08:55 IST


def ist(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def d0(hh: int, mm: int = 0) -> datetime:
    return ist(2026, 10, 12, hh, mm)


QUOTE_CLOSED = frozenset({"won", "lost", "cancelled", "archived", "deleted"})
#: source types the world registers a fake reader for while installed (everything else is the real module's)
FAKE_READERS = ("sales.quote", "sales.customer_message", "sales.enquiry")
#: approval kinds the world registers a fake handler for while installed
FAKE_HANDLERS = ("sales.quote.review",)
#: the last real seed ``bare_world`` runs (identity 10, org 12: company, people and calendar)
BARE_MAX_ORDER = 12


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


CONTACTS = {"NORDHAUS": "Lena Brandt", "MAISON": "Camille Laurent", "BERG": "Erik Lindqvist", "THORNBURY": "Oliver Hart"}


class FakeWorld:
    """The seeded company (real modules) plus the fake sales records and their event history up to D0 08:55."""

    def __init__(self, clock: FrozenClock) -> None:
        self.clock = clock
        self.refs: dict[str, uuid.UUID] = {}
        self.company_id: uuid.UUID | None = None
        self.branch_ho: uuid.UUID | None = None
        self.branch_fac: uuid.UUID | None = None
        self.quotes: dict[str, QuoteRec] = {}
        self.messages: dict[str, MessageRec] = {}
        self.enquiries: dict[str, EnquiryRec] = {}
        self.approved: list[uuid.UUID] = []
        self.ctx: SeedContext | None = None
        self._saved: tuple[Any, dict[str, Any], dict[str, Any]] | None = None

    def clone(self, clock: FrozenClock) -> FakeWorld:
        """A copy with independent fake records (the database part is shared through the snapshot)."""
        import copy

        other = FakeWorld(clock)
        for name in ("refs", "quotes", "messages", "enquiries", "approved"):
            setattr(other, name, copy.deepcopy(getattr(self, name)))
        other.company_id, other.branch_ho, other.branch_fac = self.company_id, self.branch_ho, self.branch_fac
        if self.ctx is not None:
            other.ctx = SeedContext(company_id=self.ctx.company_id, clock=clock, refs=other.refs,
                                    facts=copy.deepcopy(self.ctx.facts), slice_max=self.ctx.slice_max)
        return other

    # ---- identity (real) -----------------------------------------------------------------------------
    def key_of(self, user_id: uuid.UUID | None) -> str | None:
        for key, value in self.refs.items():
            if value == user_id and key in keys.PEOPLE:
                return key
        return None

    def actor(self, person: str, *, channel: str = "test") -> ActorContext:
        """The real effective context of a persona (identity's member-actor builder)."""
        assert self.company_id is not None, "world not built"
        return actors.actor_for_member(self.company_id, self.refs[person], channel=channel)  # type: ignore[arg-type]

    def override(self, person: str, permissions: dict[str, Scope | None]) -> None:
        """Revoke (``None``) or grant (a scope) keys for one persona, as real override rows.

        The rows are written directly and the authz epoch is bumped, so the real builder resolves them; like the
        former in-memory edits, no identity events are emitted (tests that need
        ``identity.permission_override.changed`` emit it themselves).
        """
        self._write_overrides({person: permissions}, replace=False)

    def set_overrides(self, overrides: dict[str, dict[str, Scope | None]]) -> None:
        """Replace every open override of the world's company with ``overrides`` (person -> {key: scope})."""
        self._write_overrides(overrides, replace=True)

    def _write_overrides(self, overrides: dict[str, dict[str, Scope | None]], *, replace: bool) -> None:
        from sqlalchemy import select

        from app.platform.identity.models import UserPermissionOverride
        from app.platform.identity.provisioning import bump_authz_epoch

        with self.uow() as uow:
            now = uow.now()
            for row in uow.session.scalars(select(UserPermissionOverride).where(UserPermissionOverride.archived_at.is_(None))):
                person = self._membership_key(row.membership_id)
                if replace or (person in overrides and row.permission_key in overrides[person]):
                    row.archived_at = now
            uow.flush()
            for person, perms in overrides.items():
                for key, scope in perms.items():
                    uow.add(UserPermissionOverride(
                        id=uuid.uuid7(), company_id=self.company_id, membership_id=self.refs[f"{person}_MEMBERSHIP"],
                        permission_key=key, effect="revoke" if scope is None else "grant",
                        scope=None if scope is None else scope.label, reason="test world override",
                    ))
            uow.flush()
            bump_authz_epoch(uow)

    # ---- fake source readers ------------------------------------------------------------------------
    def _party(self, key: str) -> tuple[uuid.UUID, str]:
        return self.refs[key], keys.PARTY_NAMES[key]

    def read_quote(self, _uow: UnitOfWork, source_id: uuid.UUID) -> SourceFacts | None:
        q = next((q for q in self.quotes.values() if q.id == source_id), None)
        if q is None or q.status == "deleted":
            return None
        party_id, party_name = self._party(q.party)
        valid_end = (
            datetime.combine(q.valid_until + timedelta(days=1), time(0, 0), tzinfo=IST).astimezone(UTC) if q.valid_until else None
        )
        return SourceFacts(
            source_type="sales.quote", source_id=q.id, version=q.version, label=f"{q.number} · {party_name}", status=q.status,
            owner_user_id=self.refs[q.owner], branch_id=self.branch_ho, required_permission="sales.quote.read",
            canonical_path=f"/sales/quotes/{q.id}", is_closed=q.status in QUOTE_CLOSED,
            deadlines={"valid_until_end": valid_end} if valid_end else {},
            facts={
                "quote_number": q.number, "party_name": party_name, "party_id": str(party_id),
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
        party_id, party_name = self._party(m.party)
        return SourceFacts(
            source_type="sales.customer_message", source_id=m.id, version=m.version,
            label=f"Message from {m.contact} ({party_name})", status=m.status, owner_user_id=self.refs[m.assignee],
            branch_id=self.branch_ho, required_permission="sales.customer_message.read",
            canonical_path=f"/sales/messages/{m.id}",
            facts={
                "party_id": str(party_id), "party_name": party_name, "contact_name": m.contact, "channel": m.channel,
                "received_at": m.received_at.isoformat(), "replied_at": m.replied_at.isoformat() if m.replied_at else None,
                "linked_quote_ids": [str(self.quotes[k].id) for k in m.linked_quotes],
            },
        )

    def read_enquiry(self, _uow: UnitOfWork, source_id: uuid.UUID) -> SourceFacts | None:
        e = next((e for e in self.enquiries.values() if e.id == source_id), None)
        if e is None:
            return None
        _party_id, party_name = self._party(e.party)
        return SourceFacts(
            source_type="sales.enquiry", source_id=e.id, version=e.version, label=f"{e.number} · {party_name}",
            status=e.status, owner_user_id=self.refs[e.owner], branch_id=self.branch_ho,
            required_permission="sales.enquiry.read", canonical_path=f"/sales/enquiries/{e.id}",
            is_closed=e.status in ("quoted", "closed"),
            facts={"enquiry_number": e.number, "party_name": party_name, "received_at": e.received_at.isoformat(),
                   "channel": e.channel},
        )

    def _membership_key(self, membership_id: uuid.UUID) -> str | None:
        """Persona key of a membership (the identity seed records ids in ``facts["memberships"]``)."""
        for k, v in self.refs.items():
            if k.endswith("_MEMBERSHIP") and v == membership_id:
                return k.removesuffix("_MEMBERSHIP")
        if self.ctx is not None:
            for k, v in (self.ctx.facts.get("memberships") or {}).items():
                if v == str(membership_id):
                    return k
        return None

    # ---- install / uninstall (fixture-scoped) ---------------------------------------------------------
    def install(self) -> None:
        """Register the fake readers and handler, remembering what they replace (restored by ``uninstall``)."""
        from app.platform.identity.access import ACCESS_CACHE
        from app.registry import get_registry

        get_registry()  # the real modules' on_load registrations come first, whatever the fixture scope
        assert self._saved is None, "world already installed"
        self._saved = (
            actors._builder,
            {t: sources._READERS.get(t) for t in FAKE_READERS},
            {k: approvals._HANDLERS.get(k) for k in FAKE_HANDLERS},
        )
        ACCESS_CACHE.clear()  # world tests reuse membership ids and epochs across rolled-back transactions
        sources.register_reader("sales.quote", self.read_quote)
        sources.register_reader("sales.customer_message", self.read_message)
        sources.register_reader("sales.enquiry", self.read_enquiry)
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
        """Restore every registry entry ``install`` replaced (safe to call when not installed)."""
        from app.platform.identity.access import ACCESS_CACHE

        if self._saved is None:
            return
        builder, readers, handlers = self._saved
        self._saved = None
        actors.register_member_actor_builder(builder)
        for source_type, reader in readers.items():
            if reader is None:
                sources._READERS.pop(source_type, None)
            else:
                sources._READERS[source_type] = reader
        for kind, handler in handlers.items():
            if handler is None:
                approvals._HANDLERS.pop(kind, None)
            else:
                approvals._HANDLERS[kind] = handler
        ACCESS_CACHE.clear()

    @contextmanager
    def installed(self) -> Iterator[FakeWorld]:
        self.install()
        try:
            yield self
        finally:
            self.uninstall()

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

    def party_version(self, key: str) -> int:
        """The current version of a seeded party, through the real ``parties.party`` reader."""
        with self.uow() as uow:
            facts = sources.read(uow, "parties.party", self.refs[key])
        assert facts is not None and facts.version is not None
        return facts.version

    def change_party_contacts(self, person: str, key: str, *, phone: str) -> int:
        """A real contacts change through the parties service (emits ``parties.party.updated``); returns the
        new party version."""
        from app.modules.parties import service as parties
        from app.modules.parties.schemas import ContactIn, PartyUpdate

        with self.uow(person) as uow:
            current = parties.get_party(uow, self.refs[key])
            contacts = [ContactIn(id=c.id, name=c.name, job_title=c.job_title, email=c.email, phone=phone,
                                  is_primary=c.is_primary) for c in current.contacts]
            return parties.update_party(uow, current.id, PartyUpdate(expected_version=current.version, contacts=contacts)).version

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

    # ---- fake sales history (SeedDefs merged into the real seed order) ----------------------------------
    def _quote(self, key: str, number: str, party: str, owner: str, status: str, amount: str, currency: str,
               created_at: datetime, **extra: Any) -> QuoteRec:
        q = QuoteRec(id=uuid.uuid7(), number=number, party=party, owner=owner, status=status, amount=amount, currency=currency,
                     created_at=created_at, **extra)
        self.quotes[key] = q
        self.refs[key] = q.id
        return q

    def fake_sales_seeds(self) -> list[SeedDef]:
        """Stand-ins for the sales module's seeds at the orders that keep the fixture times moving forward:
        50 (sales history, after pricing 40), 56 (after the parties change of D-1 10:05) and 76 (after Arjun's
        activation at D0 08:00)."""
        return [
            SeedDef(name="test.sales.history", order=50, run=lambda _ctx: self.build_sales_history()),
            SeedDef(name="test.sales.messages", order=56, run=lambda _ctx: self.build_messages()),
            SeedDef(name="test.sales.d0_morning", order=76, run=lambda _ctx: self.build_d0_morning()),
        ]

    def build_sales_history(self) -> None:
        """Quotes and enquiries of fixtures.md §7 up to D-3, in allocation order and time."""
        q = self._quote
        q("Q_BERG_WON", keys.QUOTES.BERG_WON, "BERG", "MEERA", "won", "5700.00", "EUR", ist(2026, 7, 24, 11))
        q("Q_THORNBURY_LOST", keys.QUOTES.THORNBURY_LOST, "THORNBURY", "NEHA", "lost", "5250.00", "GBP", ist(2026, 8, 3, 11))
        q("PRIOR_WON", keys.QUOTES.PRIOR_WON, "NORDHAUS", "MEERA", "won", "5760.00", "EUR", ist(2026, 8, 13, 11))

        self.at(ist(2026, 9, 8, 10, 0))  # ENQ-2026-0001 (D-34)
        self.enquiries["ENQ_MAISON"] = EnquiryRec(uuid.uuid7(), keys.ENQUIRIES.MAISON, "MAISON", "MEERA", ist(2026, 9, 8, 10), "email")
        self.refs["ENQ_MAISON"] = self.enquiries["ENQ_MAISON"].id
        e = self.enquiries["ENQ_MAISON"]
        self.emit("MEERA", "sales.enquiry.received", e.id, {"enquiry_id": str(e.id), "enquiry_number": e.number,
                  "party_id": str(self.refs["MAISON"]), "channel": "email", "owner_user_id": str(self.refs["MEERA"])}, version=1)
        self.drain()

        self.at(ist(2026, 9, 9, 11, 0))  # LK-QT-2026-0004
        q4 = q("Q_THORNBURY_EXPIRING", keys.QUOTES.THORNBURY_EXPIRING, "THORNBURY", "NEHA", "draft", "5880.00", "GBP", ist(2026, 9, 9, 11))
        self.emit_quote("NEHA", "sales.quote.created", "Q_THORNBURY_EXPIRING", quote_number=q4.number,
                        owner_user_id=str(self.refs["NEHA"]), party_id=str(self.refs["THORNBURY"]))
        self.drain()

        self.at(ist(2026, 9, 10, 12, 0))  # LK-QT-2026-0005 from ENQ-2026-0001
        q5 = q("Q_MAISON_OVERRIDE", keys.QUOTES.MAISON_OVERRIDE, "MAISON", "MEERA", "draft", "5280.00", "EUR", ist(2026, 9, 10, 12))
        self.emit_quote("MEERA", "sales.quote.created", "Q_MAISON_OVERRIDE", quote_number=q5.number,
                        owner_user_id=str(self.refs["MEERA"]), party_id=str(self.refs["MAISON"]), enquiry_id=str(e.id))
        e.status, e.version = "quoted", e.version + 1
        self.emit("MEERA", "sales.enquiry.quoted", e.id, {"enquiry_id": str(e.id), "quote_id": str(q5.id)}, version=e.version)
        self.drain()

        self.at(ist(2026, 9, 11, 11, 0))  # LK-QT-2026-0006
        q6 = q("Q_BERG_EXPIRING", keys.QUOTES.BERG_EXPIRING, "BERG", "MEERA", "draft", "5700.00", "EUR", ist(2026, 9, 11, 11))
        self.emit_quote("MEERA", "sales.quote.created", "Q_BERG_EXPIRING", quote_number=q6.number,
                        owner_user_id=str(self.refs["MEERA"]), party_id=str(self.refs["BERG"]))
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
                  "party_id": str(self.refs["THORNBURY"]), "channel": "phone", "owner_user_id": str(self.refs["NEHA"])}, version=1)
        self.drain()

        self.at(ist(2026, 10, 9, 12, 0))  # LK-QT-2026-0007 (D-3) from ENQ-2026-0002
        q7 = q("Q_THORNBURY_OVERRIDE", keys.QUOTES.THORNBURY_OVERRIDE, "THORNBURY", "NEHA", "draft", "5850.00", "GBP", ist(2026, 10, 9, 12))
        self.emit_quote("NEHA", "sales.quote.created", "Q_THORNBURY_OVERRIDE", quote_number=q7.number,
                        owner_user_id=str(self.refs["NEHA"]), party_id=str(self.refs["THORNBURY"]), enquiry_id=str(e2.id))
        e2.status, e2.version = "quoted", e2.version + 1
        self.emit("NEHA", "sales.enquiry.quoted", e2.id, {"enquiry_id": str(e2.id), "quote_id": str(q7.id)}, version=e2.version)
        self.drain()
        # Maison's shipping address change (D-1 10:05) is the real parties seed ``parties.world.changes`` (55)

    def build_messages(self) -> None:
        """The two customer messages of D-1 evening (after the Maison change at 10:05)."""
        for key, party, at, linked in (("MSG_BERG", "BERG", ist(2026, 10, 11, 17, 40), ["Q_BERG_EXPIRING"]),
                                       ("MSG_NORDHAUS", "NORDHAUS", ist(2026, 10, 11, 19, 20), [])):
            self.at(at)
            m = MessageRec(uuid.uuid7(), party, CONTACTS[party], "MEERA", at, linked_quotes=list(linked))
            self.messages[key] = m
            self.refs[key] = m.id
            self.emit("MEERA", "sales.customer_message.received", m.id, {
                "message_id": str(m.id), "party_id": str(self.refs[party]), "contact_id": None, "channel": "email",
                "assignee_user_id": str(self.refs["MEERA"]), "enquiry_id": None,
                "quote_id": str(self.quotes[linked[0]].id) if linked else None}, version=m.version)
            self.drain()

    def build_d0_morning(self) -> None:
        """D0 08:15-08:45, after Arjun's activation at 08:00 (identity.activation, 75)."""
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
                        owner_user_id=str(self.refs["MEERA"]), party_id=str(self.refs["NORDHAUS"]),
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

    # ---- build ------------------------------------------------------------------------------------------
    def seeds(self, *, max_order: int | None = None, names: tuple[str, ...] | None = None) -> list[SeedDef]:
        """The installed modules' seeds (``registry.seeds``, as ``lk seed demo`` selects them) plus the fake
        sales seeds, in ``(order, name)`` order."""
        from app.seed.runner import installed_seeds

        chosen = [
            s for s in (*installed_seeds(1), *self.fake_sales_seeds())
            if (max_order is None or s.order <= max_order) and (names is None or s.name in names)
        ]
        return sorted(chosen, key=lambda s: (s.order, s.name))

    def _run(self, seeds: list[SeedDef]) -> None:
        """Run seeds as ``app.seed.runner.run_demo_seed`` does: each one, then drain the outbox and jobs."""
        assert self.ctx is not None
        for seed in seeds:
            seed.run(self.ctx)
            self.drain()
            if seed.order == 10:
                self._record_identity()

    def _record_identity(self) -> None:
        """Memberships and branches from the identity seed's facts, under the keys tests use."""
        assert self.ctx is not None
        for key, membership_id in (self.ctx.facts.get("memberships") or {}).items():
            self.refs[f"{key}_MEMBERSHIP"] = uuid.UUID(membership_id)
        branches = self.ctx.facts.get("branches") or {}
        self.branch_ho = uuid.UUID(branches[keys.BRANCHES.HO])
        self.branch_fac = uuid.UUID(branches[keys.BRANCHES.FAC])

    def build(self, *, max_order: int | None = None) -> FakeWorld:
        """Install the fakes and seed the world up to ``max_order`` (all seeds by default) as ``lk seed demo``
        does; the caller uninstalls (fixtures do it in ``finally``)."""
        from app.seed.world.identity import ensure_demo_company

        if self._saved is None:
            self.install()
        self.company_id = ensure_demo_company(self.clock, D0)
        self.ctx = SeedContext(company_id=self.company_id, clock=self.clock, refs=self.refs, slice_max=1)
        self.ctx.facts["d0"] = D0
        self.ctx.facts["anchor_date"] = D0.date().isoformat()
        self._run(self.seeds(max_order=max_order))
        self.at(D0)
        self.drain()
        return self

    def run_seeds(self) -> SeedContext:
        """Re-run the tasks and briefings seeds (idempotency checks)."""
        assert self.ctx is not None
        self._run(self.seeds(names=("tasks", "briefings")))
        self.at(D0)
        return self.ctx
