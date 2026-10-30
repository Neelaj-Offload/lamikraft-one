"""Quote settings (API-35, UI-92): the ``quote_defaults`` singleton plus the numbering display.

The defaults live in the platform setting ``quote_defaults`` (versioned, audited, validated against the configured
brands); this facade reads and writes it with ``sales.quote_settings.manage`` and adds read-only previews of the next
quote, custom-product and sample numbers (``numbering.preview`` never allocates a number).
"""

from __future__ import annotations

from typing import Any

from app.modules.sales import events as ev
from app.modules.sales.common import business_date
from app.modules.sales.schemas import Capability, QuoteSettingsRead, QuoteSettingsUpdate
from app.platform.numbering import service as numbering
from app.platform.org import service as org
from app.platform.service import query
from app.platform.uow import UnitOfWork

KEY = "quote_defaults"
MANAGE = "sales.quote_settings.manage"


@query("sales.quote.read")
def get_quote_settings(uow: UnitOfWork) -> QuoteSettingsRead:
    setting = org.get_setting(uow, KEY)
    brands = [b["token"] for b in org.get_setting(uow, "brands").value.get("brands", [])]
    day = business_date(uow)
    can_manage = uow.actor.can(MANAGE)
    quote_seq = numbering._ensure_sequence(uow, ev.QUOTE_SEQUENCE.key, None)
    return QuoteSettingsRead(
        defaults=setting.value,
        version=setting.version,
        brands=brands,
        next_quote_numbers={b: numbering.preview(uow, ev.QUOTE_SEQUENCE.key, document_date=day, tokens={"brand": b}) for b in brands},
        next_custom_product_code=numbering.preview(uow, ev.CUSTOM_PRODUCT_SEQUENCE.key, document_date=day, tokens={}),
        next_sample_number=numbering.preview(uow, ev.SAMPLE_SEQUENCE.key, document_date=day, tokens={}),
        quote_sequence_reset_policy=quote_seq.reset_policy,
        capabilities={"manage": Capability(allowed=can_manage, reason_code=None if can_manage else "permission_denied")},
    )


def update_quote_settings(uow: UnitOfWork, data: QuoteSettingsUpdate) -> QuoteSettingsRead:
    """Validated write of the defaults (unknown fields, bad brands and out-of-range validity are 422; stale is 409)."""
    uow.actor.require(MANAGE)
    value: dict[str, Any] = dict(data.defaults)
    org.update_setting(uow, KEY, value=value, expected_version=data.expected_version, change_reason=data.change_reason)
    return get_quote_settings(uow)
