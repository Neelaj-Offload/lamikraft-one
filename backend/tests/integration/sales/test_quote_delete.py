"""Deleting drafts (PERM-06, PERM-22, LM-59): admin only, never-issued drafts only, numbers never reused."""

from __future__ import annotations

import pytest

from app.core.errors import Forbidden, NotFound
from app.modules.sales import service as sales
from app.modules.sales.schemas import QuoteCreate, QuoteFilters
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db


def test_delete_requires_permission_and_draft_never_issued(world: SalesWorld) -> None:
    d = world.new_draft(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    assert d.capabilities["delete"].allowed is False and d.capabilities["delete"].reason_code == "permission_denied"
    for person in (keys.USERS.MEERA, keys.USERS.SAHIL):  # sales and management hold no sales.quote.delete
        with pytest.raises(Forbidden):
            with world.uow(person) as uow:
                sales.delete_quote(uow, d.id, expected_version=d.version)
    with world.uow(keys.USERS.PRIYA) as uow:
        admin_view = sales.get_quote(uow, d.id)
    assert admin_view.capabilities["delete"].allowed
    sent = world.transition(keys.USERS.MEERA, d.id, "mark_sent")
    with world.uow(keys.USERS.PRIYA) as uow:
        issued = sales.get_quote(uow, d.id)
    assert issued.capabilities["delete"].reason_code == "issued_documents_cannot_be_deleted"
    with pytest.raises(Forbidden) as exc:
        with world.uow(keys.USERS.PRIYA) as uow:
            sales.delete_quote(uow, d.id, expected_version=sent.version)
    assert exc.value.code == "issued_documents_cannot_be_deleted"


def test_soft_delete_keeps_number_reserved(world: SalesWorld) -> None:
    d = world.new_draft(keys.USERS.MEERA, "NORDHAUS", ("OAK_TRAY", "240"))
    with world.uow(keys.USERS.PRIYA) as uow:
        deleted = sales.detail(uow, sales.delete_quote(uow, d.id, expected_version=d.version))
    assert deleted.deleted_at is not None and deleted.capabilities["update"].reason_code == "quote_deleted"
    with pytest.raises(NotFound):  # gone from reads and lists
        with world.uow(keys.USERS.MEERA) as uow:
            sales.get_quote(uow, d.id)
    with world.uow(keys.USERS.MEERA) as uow:
        assert [q.id for q in sales.list_quotes(uow, QuoteFilters()).items] == []
        assert [q.id for q in sales.list_quotes(uow, QuoteFilters(include_deleted=True)).items] == [d.id]
        next_quote = sales.create_quote(uow, QuoteCreate(party_id=world.ref("NORDHAUS")))
    assert next_quote.quote_number == "LK-QT-2026-0002" and d.quote_number == "LK-QT-2026-0001"
    events = [e for e in _event_names(world, d.id)]
    assert events[-1] == "sales.quote.deleted"


def _event_names(world: SalesWorld, quote_id):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app.platform.events.models import DomainEvent

    with world.uow(keys.USERS.SAHIL) as uow:
        return list(uow.session.scalars(select(DomainEvent.event_type).where(DomainEvent.aggregate_id == quote_id).order_by(DomainEvent.seq)))
