"""Fixture enquiries, customer messages, quotes and review proposals (docs/architecture/fixtures.md §7.1–§7.4),
created through the sales services as the acting personas with the clock at each fact's time.

Quotes are created in the stated order so the real allocator yields LK-QT-2026-0001 … 0008; issue dates give
the validity (0004 and 0006 sent Sat 2026-09-12, 30 days -> valid until 2026-10-12); 0005/0007/0008 are in
``internal_review`` with proposals submitted at D0 08:20 / 08:30 / 08:45 (refs ``PROP_MAISON``,
``PROP_THORNBURY``, ``PROP_NORDHAUS``); 0008 is drafted by Meera's assistant (origin ``agent``) from
``MSG_NORDHAUS`` at D0 08:40. Re-running is idempotent: every record carries ``origin_ref = seed:<KEY>``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.modules.parties import service as parties
from app.modules.sales import service as sales
from app.modules.sales.models import CustomerMessage, Enquiry, Quote
from app.modules.sales.schemas import (
    CustomerMessageCreate,
    DraftQuoteInput,
    DraftQuoteLine,
    EnquiryCreate,
    QuoteCreate,
    QuoteLineCreate,
    QuoteLineUpdate,
    QuoteStatus,
    QuoteTransition,
)
from app.platform.authz.actors import actor_for_member
from app.platform.uow import UnitOfWork
from app.seed.context import SeedContext
from app.seed.world import keys
from app.seed.world.parties import as_member, at_ist

SEED = "seed"
IST = ZoneInfo(keys.ZONE)


def ist(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


def _ref(key: str) -> str:
    return f"{SEED}:{key}"


@dataclass(frozen=True)
class FixtureLine:
    product: str  # keys.PRODUCTS attribute
    quantity: str
    override_price: str | None = None
    override_reason: str | None = None
    override_at: datetime | None = None  # None: at creation


@dataclass(frozen=True)
class FixtureQuote:
    key: str  # keys.QUOTES attribute / refs key
    party: str
    owner: str
    created: datetime
    line: FixtureLine
    sent: datetime | None = None
    won: datetime | None = None
    lost: datetime | None = None
    lost_reason: str | None = None
    enquiry: str | None = None  # refs key of the enquiry it answers
    review_at: datetime | None = None
    proposal_ref: str | None = None


#: §7.3, in creation order (the allocator yields the numbers in keys.QUOTES)
SLICE1_QUOTES: tuple[FixtureQuote, ...] = (
    FixtureQuote("Q_BERG_WON", "BERG", keys.USERS.MEERA, ist(2026, 7, 24, 11, 0),
                 FixtureLine("MAPLE_TRIVET", "600"), sent=ist(2026, 7, 25, 10, 0),
                 won=ist(2026, 8, 3, 11, 0)),
    FixtureQuote("Q_THORNBURY_LOST", "THORNBURY", keys.USERS.NEHA, ist(2026, 8, 3, 11, 0),
                 FixtureLine("OAK_TRAY", "250"), sent=ist(2026, 8, 4, 10, 0),
                 lost=ist(2026, 8, 20, 11, 0), lost_reason="price"),
    FixtureQuote("PRIOR_WON", "NORDHAUS", keys.USERS.MEERA, ist(2026, 8, 13, 11, 0),
                 FixtureLine("OAK_TRAY", keys.EXPECTED.SCENARIO_C_QTY), sent=ist(2026, 8, 14, 10, 0),
                 won=ist(2026, 8, 21, 11, 0)),
    FixtureQuote("Q_THORNBURY_EXPIRING", "THORNBURY", keys.USERS.NEHA, ist(2026, 9, 9, 11, 0),
                 FixtureLine("OAK_TRAY", "280"), sent=ist(2026, 9, 12, 9, 30)),
    FixtureQuote("Q_MAISON_OVERRIDE", "MAISON", keys.USERS.MEERA, ist(2026, 9, 10, 12, 0),
                 FixtureLine("ASH_BOARD", "320", "16.5000", "Volume price agreed for launch order", at_ist(0, 8, 15)),
                 enquiry="ENQ_MAISON", review_at=at_ist(0, 8, 20), proposal_ref=keys.PROPOSALS.MAISON),
    FixtureQuote("Q_BERG_EXPIRING", "BERG", keys.USERS.MEERA, ist(2026, 9, 11, 11, 0),
                 FixtureLine("MAPLE_TRIVET", "600"), sent=ist(2026, 9, 12, 10, 0)),
    FixtureQuote("Q_THORNBURY_OVERRIDE", "THORNBURY", keys.USERS.NEHA, at_ist(-3, 12, 0),
                 FixtureLine("OAK_TRAY", "300", "19.5000", "Dealer volume discount requested"),
                 enquiry="ENQ_THORNBURY", review_at=at_ist(0, 8, 30), proposal_ref=keys.PROPOSALS.THORNBURY),
)

#: §7.1 enquiries: (refs key, party, owner, received, channel, subject)
SLICE1_ENQUIRIES: tuple[tuple[str, str, str, datetime, str, str], ...] = (
    ("ENQ_MAISON", "MAISON", keys.USERS.MEERA, at_ist(-34, 10, 0), "email", "Ash chopping boards for the launch range"),
    ("ENQ_THORNBURY", "THORNBURY", keys.USERS.NEHA, at_ist(-5, 15, 0), "phone", "Oak trays, dealer pricing"),
)

#: §7.2 messages: (refs key, party, assignee, received, linked quote key, subject, body)
SLICE1_MESSAGES: tuple[tuple[str, str, str, datetime, str | None, str, str], ...] = (
    (keys.MESSAGES.BERG, "BERG", keys.USERS.MEERA, at_ist(-1, 17, 40), "Q_BERG_EXPIRING", "Re: LK-QT-2026-0006",
     "Hello Meera, could you confirm the delivery window for the trivets before we release the order? Regards, Erik"),
    (keys.MESSAGES.NORDHAUS, "NORDHAUS", keys.USERS.MEERA, at_ist(-1, 19, 20), None, "Repeat order oak trays",
     "Hi Meera, we would like to repeat our usual oak tray order. Please send a fresh quotation. Best, Lena"),
)

NORDHAUS_DRAFT_AT = at_ist(0, 8, 40)
NORDHAUS_REVIEW_AT = at_ist(0, 8, 45)


def _settle(ctx: SeedContext) -> None:
    """Deliver the events of the fact just created at its own time (the tasks rules re-read the sources, so an
    obligation that opened and closed before the next fact must be seen while it is open), as the fixture
    history happened one fact at a time."""
    from app.platform.jobs.worker import drain
    from app.seed.world.tasks import seed_clock

    with seed_clock(ctx):
        drain()


def _find(uow: UnitOfWork, model: type, key: str) -> uuid.UUID | None:
    return uow.session.scalar(select(model.id).where(model.company_id == uow.actor.company_id, model.origin_ref == _ref(key)))


def _quote_status(uow: UnitOfWork, quote_id: uuid.UUID) -> tuple[str, int, uuid.UUID | None]:
    row = uow.session.execute(select(Quote.status, Quote.version, Quote.review_proposal_id).where(Quote.id == quote_id)).one()
    return row[0], row[1], row[2]


def _seed_enquiries(ctx: SeedContext) -> None:
    for key, party, owner, received, channel, subject in SLICE1_ENQUIRIES:
        ctx.at(received)
        with as_member(ctx, owner) as uow:
            existing = _find(uow, Enquiry, key)
            if existing is not None:
                ctx.refs[key] = existing
                continue
            detail = parties.get_party(uow, ctx.ref(party))
            contact = next((c for c in detail.contacts if c.is_primary), None)
            created = sales.create_enquiry(
                uow,
                EnquiryCreate(
                    party_id=detail.id, contact_id=contact.id if contact else None, channel=channel,  # type: ignore[arg-type]
                    received_at=received, subject=subject,
                    body=f"{subject}. Please quote at your earliest convenience.",
                ),
                origin=SEED,
                origin_ref=_ref(key),
            )
            ctx.refs[key] = created.id
        _settle(ctx)


def _create_quote(ctx: SeedContext, spec: FixtureQuote) -> uuid.UUID:
    quote_id = _create_quote_once(ctx, spec)
    _settle(ctx)
    return quote_id


def _create_quote_once(ctx: SeedContext, spec: FixtureQuote) -> uuid.UUID:
    ctx.at(spec.created)
    with as_member(ctx, spec.owner) as uow:
        existing = _find(uow, Quote, spec.key)
        if existing is not None:
            return existing
        quote = sales.create_quote(
            uow,
            QuoteCreate(party_id=ctx.ref(spec.party), enquiry_id=ctx.ref(spec.enquiry) if spec.enquiry else None),
            origin=SEED,
            origin_ref=_ref(spec.key),
        )
        line = spec.line
        at_creation = line.override_price is not None and line.override_at is None
        sales.add_line(
            uow,
            quote.id,
            QuoteLineCreate(
                expected_version=quote.version,
                product_id=ctx.ref(line.product),
                quantity=Decimal(line.quantity),
                unit_price=Decimal(line.override_price) if at_creation else None,
                override_reason=line.override_reason if at_creation else None,
            ),
            origin=SEED,
        )
        return quote.id


def _transition(ctx: SeedContext, person: str, quote_id: uuid.UUID, at: datetime, action: str, **extra: object) -> None:
    ctx.at(at)
    actor = actor_for_member(ctx.company_id, ctx.ref(person), channel="cli").with_(idempotency_key=f"seed:{quote_id}:{action}")
    with UnitOfWork(actor, clock=ctx.clock) as uow:
        _status, version, _proposal = _quote_status(uow, quote_id)
        sales.transition_quote(uow, quote_id, QuoteTransition(action=action, expected_version=version, **extra), origin=SEED)  # type: ignore[arg-type]
    _settle(ctx)


def _history(ctx: SeedContext, spec: FixtureQuote, quote_id: uuid.UUID) -> None:
    with as_member(ctx, spec.owner) as uow:
        status, _version, _proposal = _quote_status(uow, quote_id)
    if spec.sent and status == QuoteStatus.DRAFT.value:
        _transition(ctx, spec.owner, quote_id, spec.sent, "mark_sent", dispatch_channel="email")
        status = QuoteStatus.SENT.value
    if spec.won and status == QuoteStatus.SENT.value:
        _transition(ctx, spec.owner, quote_id, spec.won, "mark_won")
    if spec.lost and status == QuoteStatus.SENT.value:
        _transition(ctx, spec.owner, quote_id, spec.lost, "mark_lost", reason_code=spec.lost_reason, reason="Customer chose a lower-priced offer")


def _late_override(ctx: SeedContext, spec: FixtureQuote, quote_id: uuid.UUID) -> None:
    line = spec.line
    if line.override_price is None or line.override_at is None:
        return
    ctx.at(line.override_at)
    with as_member(ctx, spec.owner) as uow:
        status, version, _proposal = _quote_status(uow, quote_id)
        if status != QuoteStatus.DRAFT.value:
            return
        detail = sales.get_quote(uow, quote_id)
        first = detail.lines[0]
        if first.unit_price == Decimal(line.override_price):
            return
        sales.update_line(
            uow, quote_id, first.id,
            QuoteLineUpdate(expected_version=version, unit_price=Decimal(line.override_price), override_reason=line.override_reason),
            origin=SEED,
        )
    _settle(ctx)


def _review(ctx: SeedContext, person: str, quote_id: uuid.UUID, at: datetime, proposal_ref: str) -> None:
    with as_member(ctx, person) as uow:
        status, _version, proposal_id = _quote_status(uow, quote_id)
    if status == QuoteStatus.INTERNAL_REVIEW.value and proposal_id is not None:
        ctx.refs[proposal_ref] = proposal_id
        return
    if status != QuoteStatus.DRAFT.value:
        return
    _transition(ctx, person, quote_id, at, "submit_review")
    with as_member(ctx, person) as uow:
        _status, _version, proposal_id = _quote_status(uow, quote_id)
    assert proposal_id is not None
    ctx.refs[proposal_ref] = proposal_id


def _seed_messages(ctx: SeedContext) -> None:
    for key, party, assignee, received, linked, subject, body in SLICE1_MESSAGES:
        ctx.at(received)
        with as_member(ctx, assignee) as uow:
            existing = _find(uow, CustomerMessage, key)
            if existing is not None:
                ctx.refs[key] = existing
                continue
            detail = parties.get_party(uow, ctx.ref(party))
            contact = next((c for c in detail.contacts if c.is_primary), None)
            created = sales.record_customer_message(
                uow,
                CustomerMessageCreate(
                    party_id=detail.id, contact_id=contact.id if contact else None, channel="email",  # type: ignore[arg-type]
                    received_at=received, assignee_user_id=ctx.ref(assignee),
                    quote_id=ctx.ref(linked) if linked else None, subject=subject, body=body,
                ),
                origin=SEED,
                origin_ref=_ref(key),
            )
            ctx.refs[key] = created.id
        _settle(ctx)


def _seed_nordhaus_draft(ctx: SeedContext) -> None:
    """LK-QT-2026-0008: drafted by Meera's assistant (origin agent) from MSG_NORDHAUS at D0 08:40, reviewed 08:45."""
    key = "Q_NORDHAUS_DRAFT"
    ctx.at(NORDHAUS_DRAFT_AT)
    with as_member(ctx, keys.USERS.MEERA) as uow:
        existing = _find(uow, Quote, key)
    if existing is None:
        actor = actor_for_member(ctx.company_id, ctx.ref(keys.USERS.MEERA), channel="cli").with_(actor_type="agent", idempotency_key=f"seed:{key}")
        with UnitOfWork(actor, clock=ctx.clock) as uow:
            basis = sales.find_repeat_quote_basis(uow, ctx.ref("NORDHAUS"))
            lines = [
                DraftQuoteLine(product_id=ln.product_id, quantity=ln.quantity, unit_code=ln.unit_code)  # type: ignore[arg-type]
                for ln in basis.lines
            ] or [DraftQuoteLine(product_id=ctx.ref("OAK_TRAY"), quantity=Decimal(keys.EXPECTED.SCENARIO_C_QTY))]
            draft = sales.draft_quote(
                uow,
                DraftQuoteInput(party_id=ctx.ref("NORDHAUS"), lines=lines, origin_message_id=ctx.ref(keys.MESSAGES.NORDHAUS)),
                origin="agent",
                origin_ref=_ref(key),
            )
            existing = draft.id
        _settle(ctx)
    ctx.refs[key] = existing
    _review(ctx, keys.USERS.MEERA, existing, NORDHAUS_REVIEW_AT, keys.PROPOSALS.NORDHAUS)


def seed_sales_history(ctx: SeedContext) -> None:
    """Order 50 (after pricing/commercial): enquiries and quotes 0001 … 0007 with their history up to D-3."""
    _seed_enquiries(ctx)
    for spec in SLICE1_QUOTES:
        quote_id = _create_quote(ctx, spec)
        ctx.refs[spec.key] = quote_id
        _history(ctx, spec, quote_id)


def seed_sales_messages(ctx: SeedContext) -> None:
    """Order 56 (after the Maison change of D-1 10:05, ``parties.world.changes`` 55): the D-1 evening messages."""
    _seed_messages(ctx)


def seed_sales_d0(ctx: SeedContext) -> None:
    """Order 76 (after Arjun's activation at D0 08:00, ``identity.activation`` 75): the 08:15 override, the
    08:20 / 08:30 reviews and Meera's assistant draft LK-QT-2026-0008 (08:40, review 08:45)."""
    for spec in SLICE1_QUOTES:
        quote_id = ctx.ref(spec.key)
        _late_override(ctx, spec, quote_id)
        if spec.review_at and spec.proposal_ref:
            _review(ctx, spec.owner, quote_id, spec.review_at, spec.proposal_ref)
    _seed_nordhaus_draft(ctx)


def seed_sales(ctx: SeedContext) -> None:
    """The whole sales world in one call (the three seeds above, in order)."""
    seed_sales_history(ctx)
    seed_sales_messages(ctx)
    seed_sales_d0(ctx)
