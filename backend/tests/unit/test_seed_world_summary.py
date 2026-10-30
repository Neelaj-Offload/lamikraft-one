"""``/_test/fixtures`` body (``seed.runner.world_summary``): published constants and ids by business key."""

from __future__ import annotations

import uuid

from app.core.clock import FrozenClock
from app.seed.context import SeedContext
from app.seed.runner import world_summary
from app.seed.world import keys


def test_world_summary_publishes_the_e2e_facts_and_business_key_refs() -> None:
    quote, enquiry, prior = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ctx = SeedContext(company_id=uuid.uuid4(), clock=FrozenClock(keys.CLOCK_D0), slice_max=1)
    ctx.refs.update({"Q_MAISON_OVERRIDE": quote, "ENQ_MAISON": enquiry, "PRIOR_WON": prior, keys.USERS.MEERA: uuid.uuid4()})
    body = world_summary(ctx)
    facts = body["facts"]
    assert facts["expected"]["SCENARIO_C_TOTAL"] == keys.EXPECTED.SCENARIO_C_TOTAL
    assert facts["expected"]["SCENARIO_C_QTY"] == keys.EXPECTED.SCENARIO_C_QTY
    assert "MEERA_S1_ITEM_ORDER" not in facts["expected"]  # only string constants
    assert facts["quotes"] == dict(vars(keys.QUOTES)) and facts["enquiries"] == dict(vars(keys.ENQUIRIES))
    refs = body["refs"]
    assert refs["Q_MAISON_OVERRIDE"] == refs[keys.QUOTES.MAISON_OVERRIDE] == str(quote)
    assert refs[keys.ENQUIRIES.MAISON] == str(enquiry) and refs[keys.QUOTES.PRIOR_WON] == str(prior)
    assert keys.QUOTES.NORDHAUS_DRAFT not in refs  # not seeded here: no business key either
