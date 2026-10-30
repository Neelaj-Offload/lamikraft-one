"""The canonical fixture world for tasks/briefings tests (fixtures.md §2-§7), built on real PostgreSQL.

The company is built by the **real** seeds of the installed modules, run in ``(order, name)`` order through
``registry.seeds`` exactly as ``lk seed demo`` does (``app.seed.runner``): identity (10), org (12), parties (20),
catalogue (30), pricing/commercial (40), parties changes (55), identity activation (75), tasks (80) and
briefings (81). Actors come from the real member-actor builder (identity), parties are read by the real
``parties.party`` reader, and permission edits are real override rows that the real builder resolves.

Nothing is faked any more: sales (enquiries, customer messages, quotes and the D0 reviews) comes from the real
``sales.world`` seeds (orders 50, 56 and 76) and is read by the real ``sales.*`` readers; the review handler is
the sales module's. The identity, ui and search readers (``identity.membership``, ``identity.user_preference``,
``ui.recent_record``, ``search.recent``) are the real modules' too; tests that need an onboarding step done record
the real fact (a saved preference, an opened record, a recent search). ``install``/``uninstall`` remain as the
seam guard (they save and restore the member-actor builder and the reader/handler entries named in
``FAKE_READERS``/``FAKE_HANDLERS``, now empty) and clear identity's access cache.

Tests change sales records through the sales services (``transition``, ``record_message``, ``mark_replied``,
``create_enquiry``); the Slice-2 commands sales does not ship yet (revise, extend validity, internal notes) are
stood in by ``slice2_quote_change`` (a real row update and version bump) plus the event the command would emit.
Every test reads ids from ``world.refs`` (fixture keys) and expected text from ``app.seed.world.keys.EXPECTED``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.clock import FrozenClock
from app.modules.approvals import service as approvals
from app.modules.sales.models import CustomerMessage, Quote
from app.platform import sources
from app.platform.authz import actors
from app.platform.authz.context import ActorContext
from app.platform.authz.permissions import Scope
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


#: source types the world registers a fake reader for while installed (everything else is the real module's)
FAKE_READERS: tuple[str, ...] = ()
#: approval kinds the world registers a fake handler for while installed
FAKE_HANDLERS: tuple[str, ...] = ()
#: the last real seed ``bare_world`` runs (identity 10, org 12: company, people and calendar)
BARE_MAX_ORDER = 12


class FakeWorld:
    """The seeded company (real modules, sales included) and its event history up to D0 08:55."""

    def __init__(self, clock: FrozenClock) -> None:
        self.clock = clock
        self.refs: dict[str, uuid.UUID] = {}
        self.company_id: uuid.UUID | None = None
        self.branch_ho: uuid.UUID | None = None
        self.branch_fac: uuid.UUID | None = None
        self.ctx: SeedContext | None = None
        self._saved: tuple[Any, dict[str, Any], dict[str, Any]] | None = None

    def clone(self, clock: FrozenClock) -> FakeWorld:
        """A copy with independent refs (the database part is shared through the snapshot)."""
        import copy

        other = FakeWorld(clock)
        for name in ("refs",):
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
        """Remember the seams (builder, ``FAKE_READERS``, ``FAKE_HANDLERS``) so ``uninstall`` restores them exactly."""
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

    # ---- sales (real module) -------------------------------------------------------------------------
    def quote(self, quote_key: str) -> Quote:
        """The seeded quote row (detached), read as the system."""
        with self.uow() as uow:
            row = uow.session.get(Quote, self.refs[quote_key])
            assert row is not None, quote_key
            uow.session.expunge(row)
            return row

    def message(self, message_key: str) -> CustomerMessage:
        with self.uow() as uow:
            row = uow.session.get(CustomerMessage, self.refs[message_key])
            assert row is not None, message_key
            uow.session.expunge(row)
            return row

    def emit_quote(self, person: str, name: str, quote_key: str, *, agent: bool = False, **payload: Any) -> uuid.UUID:
        """Emit a sales event for a seeded quote at the quote's current real version."""
        q = self.quote(quote_key)
        return self.emit(person, name, q.id, {"quote_id": str(q.id), **payload}, version=q.version, agent=agent)

    def slice2_quote_change(self, quote_key: str, **columns: Any) -> Quote:
        """Stand-in for the Slice-2 quote commands (revise, extend validity, internal notes) that sales does not
        ship yet: the row is updated as the system so the real reader returns the new facts and a new version; the
        caller emits the event the Slice-2 command would emit (``emit_quote``)."""
        with self.uow() as uow:
            row = uow.session.get(Quote, self.refs[quote_key])
            assert row is not None, quote_key
            for name, value in columns.items():
                setattr(row, name, value)
            row.updated_at = uow.now()  # a new version even when only unlisted fields change
            uow.flush()
            uow.session.expunge(row)
            return row

    def transition(self, person: str, quote_key: str, action: str, **extra: Any) -> Quote:
        """A real quote transition (``sales.transition_quote``) as ``person``; emits the sales events."""
        from app.modules.sales import service as sales
        from app.modules.sales.schemas import QuoteTransition

        actor = self.actor(person).with_(idempotency_key=str(uuid.uuid7()))
        with UnitOfWork(actor) as uow:
            current = uow.session.get(Quote, self.refs[quote_key])
            assert current is not None, quote_key
            data = QuoteTransition(action=action, expected_version=current.version, **extra)  # type: ignore[arg-type]
            sales.transition_quote_command(uow, self.refs[quote_key], data)
        self.drain()
        return self.quote(quote_key)

    def agent_draft(self, person: str, party: str, product: str, quantity: str, *, key: str = "Q_AGENT_DRAFT") -> Any:
        """A draft by ``person``'s assistant (actor type agent, origin agent) through ``sales.draft_quote``; returns
        the ``QuoteDetail``. ``product`` is the product's refs key (``keys.PRODUCT_NAMES``)."""
        from decimal import Decimal

        from app.modules.sales import service as sales
        from app.modules.sales.schemas import DraftQuoteInput, DraftQuoteLine

        actor = self.actor(person).with_(actor_type="agent", idempotency_key=str(uuid.uuid7()))
        with UnitOfWork(actor) as uow:
            detail = sales.draft_quote(uow, DraftQuoteInput(party_id=self.refs[party], lines=[
                DraftQuoteLine(product_id=self.refs[product], quantity=Decimal(quantity))]), origin="agent")
        self.refs[key] = detail.id
        self.drain()
        return detail

    def record_message(self, key: str, party: str, assignee: str, at: datetime, *, quote_key: str | None = None,
                       by_system: bool = False, origin: str | None = None, drain: bool = True) -> uuid.UUID:
        """A real inbound customer message (``sales.record_customer_message``) received at ``at``, recorded by the
        assignee or the system (channel processing); ``drain=False`` leaves the event in the outbox."""
        from app.modules.parties import service as parties
        from app.modules.sales import service as sales
        from app.modules.sales.schemas import CustomerMessageCreate

        self.at(at)
        with self.uow(None if by_system else assignee) as uow:
            detail = parties.get_party(uow, self.refs[party]) if not by_system else None
            contact = next((c for c in detail.contacts if c.is_primary), None) if detail else None
            created = sales.record_customer_message(uow, CustomerMessageCreate(
                party_id=self.refs[party], contact_id=contact.id if contact else None, channel="email",  # type: ignore[arg-type]
                received_at=at, assignee_user_id=self.refs[assignee],
                quote_id=self.refs[quote_key] if quote_key else None, subject="Test message", body="Test message body"),
                origin=origin)
        self.refs[key] = created.id
        if drain:
            self.drain()
        return created.id

    def touch_message(self, person: str, message_key: str) -> CustomerMessage:
        """A later source event for a message: a real edit (``sales.update_customer_message``, a new version; sales
        emits no event for it) followed by the ``received`` event re-delivered at that version, as a channel
        re-delivery would. The rules re-derive the message's obligations from the real reader."""
        from app.modules.sales import service as sales
        from app.modules.sales.schemas import CustomerMessageUpdate

        with self.uow(person) as uow:
            m = uow.session.get(CustomerMessage, self.refs[message_key])
            assert m is not None
            sales.update_customer_message(uow, m.id, CustomerMessageUpdate(expected_version=m.version,
                                                                           subject=f"{m.subject or 'Message'} (follow-up)"))
        m = self.message(message_key)
        self.emit(person, "sales.customer_message.received", m.id, {
            "message_id": str(m.id), "party_id": str(m.party_id), "contact_id": str(m.contact_id) if m.contact_id else None,
            "channel": m.channel, "assignee_user_id": str(m.assignee_user_id), "enquiry_id": None,
            "quote_id": str(m.quote_id) if m.quote_id else None}, version=m.version)
        self.drain()
        return m

    def mark_replied(self, person: str, message_key: str, at: datetime, *, drain: bool = True) -> CustomerMessage:
        from app.modules.sales import service as sales
        from app.modules.sales.schemas import MarkReplied

        self.at(at)
        with self.uow(person) as uow:
            m = uow.session.get(CustomerMessage, self.refs[message_key])
            assert m is not None
            sales.mark_replied(uow, m.id, MarkReplied(expected_version=m.version))
        if drain:
            self.drain()
        return self.message(message_key)

    def create_enquiry(self, key: str, party: str, owner: str, at: datetime, channel: str = "email") -> uuid.UUID:
        from app.modules.sales import service as sales
        from app.modules.sales.schemas import EnquiryCreate

        self.at(at)
        with self.uow(owner) as uow:
            created = sales.create_enquiry(uow, EnquiryCreate(party_id=self.refs[party], channel=channel,  # type: ignore[arg-type]
                                                              received_at=at, subject="Test enquiry"))
        self.refs[key] = created.id
        self.drain()
        return created.id

    # ---- build ------------------------------------------------------------------------------------------
    def seeds(self, *, max_order: int | None = None, names: tuple[str, ...] | None = None) -> list[SeedDef]:
        """The installed modules' seeds (``registry.seeds``, as ``lk seed demo`` selects them) in ``(order, name)``
        order."""
        from app.seed.runner import installed_seeds

        chosen = [
            s for s in installed_seeds(1)
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
        """Install (seam guard) and seed the world up to ``max_order`` (all seeds by default) as ``lk seed demo``
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
