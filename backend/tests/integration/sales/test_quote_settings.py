"""Quote settings (API-35, UI-92): the quote_defaults singleton read by everyone who reads quotes, written with
sales.quote_settings.manage (validated, versioned), plus numbering previews that never allocate a number."""

from __future__ import annotations

import pytest

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.sales import service as sales
from app.modules.sales.schemas import QuoteCreate, QuoteSettingsUpdate
from app.seed.context import D0
from app.seed.world import keys
from tests.integration.sales.world import SalesWorld

pytestmark = pytest.mark.db
MEERA, PRIYA = keys.USERS.MEERA, keys.USERS.PRIYA


def test_defaults_and_numbering_settings_validated(world: SalesWorld) -> None:
    with world.uow(MEERA) as uow:
        before = sales.get_quote_settings(uow)
    assert before.defaults["currency"] == "EUR" and before.defaults["validity_days"] == 30 and before.version == 0
    assert before.next_quote_numbers == {"LK": "LK-QT-2026-0001", "CR": "CR-QT-2026-0001"}
    assert before.next_custom_product_code == "CP-0001" and before.next_sample_number == "SMP-2026-0001"
    assert before.quote_sequence_reset_policy == "never" and not before.capabilities["manage"].allowed
    with pytest.raises(Forbidden), world.uow(MEERA, recent_auth_at=D0) as uow:
        sales.update_quote_settings(uow, QuoteSettingsUpdate(defaults=before.defaults, expected_version=0))
    with pytest.raises(ValidationFailed), world.uow(PRIYA, recent_auth_at=D0) as uow:  # unknown brand
        sales.update_quote_settings(uow, QuoteSettingsUpdate(defaults={**before.defaults, "brand": "ZZ"}, expected_version=0))
    with pytest.raises(ValidationFailed), world.uow(PRIYA, recent_auth_at=D0) as uow:  # out of range
        sales.update_quote_settings(uow, QuoteSettingsUpdate(defaults={**before.defaults, "validity_days": 0}, expected_version=0))
    with world.uow(PRIYA, recent_auth_at=D0) as uow:
        after = sales.update_quote_settings(uow, QuoteSettingsUpdate(
            defaults={**before.defaults, "validity_days": 45, "brand": "CR", "incoterm": "CIF"}, expected_version=0,
            change_reason="Crown export desk"))
    assert (after.version, after.defaults["validity_days"], after.defaults["brand"], after.capabilities["manage"].allowed) == (1, 45, "CR", True)
    with pytest.raises(Conflict), world.uow(PRIYA, recent_auth_at=D0) as uow:  # stale
        sales.update_quote_settings(uow, QuoteSettingsUpdate(defaults=after.defaults, expected_version=0))
    # new quotes take the defaults; previews never consumed a number
    with world.uow(MEERA) as uow:
        q = sales.create_quote(uow, QuoteCreate(party_id=world.ref("NORDHAUS")))
        assert (q.quote_number, q.validity_days, q.brand, q.incoterm) == ("CR-QT-2026-0001", 45, "CR", "CIF")
