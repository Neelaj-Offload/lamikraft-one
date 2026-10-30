"""``pricing`` (LM-30, FG-PRC-04/14/16, BUG-12/15): key (product_key, price_type, currency); needs the product.

Rows land in the standard list ``STD-{TYPE}-{CUR}`` through the pricing module's public services only:
- no list yet: a draft list is created and the item added (activation stays a pricing decision);
- an active list with a current item at another price: an effective-dated supersede (history kept);
- the same price: unchanged.
Situations the current public pricing API cannot express are quarantined instead of written around it: a new
product on an active list (``PRICE_LIST_ACTIVE_NEW_ITEM``), a changed price on a draft list
(``PRICE_DRAFT_ITEM_EXISTS``) and retired lists. ``price``/``final_price`` disagreeing is ``PRICE_AMBIGUOUS``; a blank
price type or currency is quarantined unless the mapping confirms a default (the legacy silent INR/domestic default is
not repeated). Orphan rows are quarantined. Price writes are not reversed by an import rollback (pricing history).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.modules.imports.definitions.base import (
    QUARANTINE,
    WARNING,
    Change,
    FieldSpec,
    ImportDefinition,
    Issue,
    Plan,
    Prepared,
    as_date,
    as_decimal,
    cell,
    currency_code,
    jsonable,
    need,
)
from app.modules.imports.definitions.products_master import uom_code
from app.modules.imports.definitions.sections import find_product, orphan
from app.platform.uow import UnitOfWork

PRICE_TYPES = ("domestic", "export", "sample", "distributor")
CURRENCIES = ("INR", "EUR", "USD", "GBP")
DECIMALS = ("base_price", "addon_price", "yield_qty_per_board", "thickness_mm", "moq")
TEXTS = ("base_price_label", "addon_price_label", "price_basis", "price_notes", "display_sku", "source_sheet",
         "source_row")


def list_code(price_type: str, currency: str) -> str:
    return f"STD-{price_type.upper()}-{currency.upper()}"


class PricingMaster(ImportDefinition):
    import_type = "pricing"
    label = "Pricing"
    description = "Standard selling prices per product, price type and currency (lists STD-TYPE-CUR)."
    fields = (
        FieldSpec("product_key", required=True),
        FieldSpec("price_type"),
        FieldSpec("currency"),
        FieldSpec("price"),
        FieldSpec("final_price"),
        *(FieldSpec(n) for n in DECIMALS),
        FieldSpec("unit_of_sale", aliases=("uom", "unit")),
        FieldSpec("valid_from"),
        FieldSpec("valid_to"),
        *(FieldSpec(n, aliases=("notes",) if n == "price_notes" else ()) for n in TEXTS),
    )
    depends_on = ("products_master",)
    writes = ("pricing_price_list", "pricing_price_list_item")

    def normalise(self, values: Mapping[str, str | None], options: Mapping[str, Any]) -> Prepared:
        issues: list[Issue] = []
        key = need(values, "product_key", issues)
        price_type = (cell(values, "price_type", issues) or "").strip().lower().replace(" ", "_") or None
        currency = currency_code(cell(values, "currency", issues), "currency", issues)
        if price_type is None and options.get("default_price_type"):
            price_type = str(options["default_price_type"])
            issues.append(Issue("DEFAULT_APPLIED", WARNING, f"price_type defaulted to {price_type}", "price_type"))
        if currency is None and options.get("default_currency"):
            currency = str(options["default_currency"])
            issues.append(Issue("DEFAULT_APPLIED", WARNING, f"currency defaulted to {currency}", "currency"))
        if price_type is None:
            issues.append(Issue("PRICE_TYPE_MISSING", QUARANTINE, "price_type is blank (confirm a default in the "
                                "mapping)", "price_type"))
        elif price_type not in PRICE_TYPES:
            issues.append(Issue("PRICE_TYPE_UNKNOWN", QUARANTINE, f"price_type '{price_type}' is not known",
                                "price_type", price_type))
        if currency is None:
            issues.append(Issue("CURRENCY_MISSING", QUARANTINE, "currency is blank (confirm a default in the mapping)",
                                "currency"))
        elif currency not in CURRENCIES:
            issues.append(Issue("CURRENCY_UNKNOWN", QUARANTINE, f"currency '{currency}' is not enabled", "currency",
                                currency))
        price = as_decimal(cell(values, "price", issues), "price", issues)
        final = as_decimal(cell(values, "final_price", issues), "final_price", issues)
        if price is not None and final is not None and price != final:
            issues.append(Issue("PRICE_AMBIGUOUS", QUARANTINE, f"price {price} and final_price {final} disagree",
                                "final_price", f"price={price}, final_price={final}"))
        unit_price = final if final is not None else price
        if unit_price is None:
            issues.append(Issue("PRICE_MISSING", QUARANTINE, "Neither price nor final_price is given", "price"))
        elif unit_price <= 0:
            issues.append(Issue("PRICE_NOT_POSITIVE", QUARANTINE, "A zero price is not imported", "price",
                                str(unit_price)))
        out: dict[str, Any] = {
            "product_key": key, "price_type": price_type, "currency": currency, "unit_price": jsonable(unit_price),
            "unit_text": cell(values, "unit_of_sale", issues),
            "valid_from": jsonable(as_date(cell(values, "valid_from", issues), "valid_from", issues)),
            "valid_to": jsonable(as_date(cell(values, "valid_to", issues), "valid_to", issues)),
        }
        for name in DECIMALS:
            out[name] = jsonable(as_decimal(cell(values, name, issues), name, issues, positive=name != "base_price"))
        for name in TEXTS:
            out[name] = cell(values, name, issues)
        natural = f"{key}|{price_type}|{currency}" if key else None
        return Prepared(values=out, key=natural, issues=issues)

    def plan(self, uow: UnitOfWork, prepared: Prepared, options: Mapping[str, Any]) -> Plan:
        from app.modules.pricing import service as pricing
        from app.modules.pricing.models import PriceListItem

        v = prepared.values
        product = find_product(uow, v["product_key"])
        if product is None:
            return orphan(v["product_key"])
        issues: list[Issue] = []
        unit = uom_code(uow, v["unit_text"], "unit_of_sale", issues) if v["unit_text"] else product.unit_of_sale
        if unit is None:
            issues.append(Issue("UNIT_MISSING", QUARANTINE, "No unit on the row or the product", "unit_of_sale"))
            return Plan("insert", issues=issues)
        if v["display_sku"] and v["display_sku"] != product.display_sku:
            issues.append(Issue("DISPLAY_SKU_MISMATCH", WARNING, f"display_sku '{v['display_sku']}' differs from the "
                                f"product's '{product.display_sku}'", "display_sku", v["display_sku"]))
        code = list_code(v["price_type"], v["currency"])
        context = {"product_id": str(product.id), "unit": unit, "list_code": code}
        price_list = pricing.find_price_list(uow, code)
        if price_list is None:
            return Plan("insert", product.id, None, {"unit_price": [None, v["unit_price"]], "list": [None, code]}, issues,
                        context)
        today = pricing.business_date(uow)
        item = uow.session.scalars(
            select(PriceListItem).where(
                PriceListItem.price_list_id == price_list.id,
                PriceListItem.product_id == product.id,
                PriceListItem.unit_code == unit,
                PriceListItem.status == "active",
                PriceListItem.superseded_by_item_id.is_(None),
            ).order_by(PriceListItem.valid_from.desc())
        ).first()
        context["price_list_id"] = str(price_list.id)
        if price_list.status == "retired":
            issues.append(Issue("PRICE_LIST_RETIRED", QUARANTINE, f"{code} is retired", "currency"))
            return Plan("insert", issues=issues, context=context)
        if item is None:
            if price_list.status == "active":
                issues.append(Issue("PRICE_LIST_ACTIVE_NEW_ITEM", QUARANTINE, f"{code} is active; a new product price "
                                    "needs the pricing import service", "product_key", v["product_key"]))
                return Plan("insert", issues=issues, context=context)
            return Plan("insert", product.id, None, {"unit_price": [None, v["unit_price"]]}, issues, context)
        context["item_id"] = str(item.id)
        if Decimal(v["unit_price"]) == item.unit_price:
            return Plan("unchanged", item.id, item.version, {}, issues, context)
        if price_list.status != "active":
            issues.append(Issue("PRICE_DRAFT_ITEM_EXISTS", QUARANTINE, f"{code} is a draft with another price for "
                                "this product; edit it in the price list", "price", v["unit_price"]))
            return Plan("insert", issues=issues, context=context)
        starts = max(date.fromisoformat(v["valid_from"]) if v["valid_from"] else today, today)
        if starts <= item.valid_from:
            issues.append(Issue("VALID_FROM_TOO_EARLY", QUARANTINE, "The new price must start after the current one",
                                "valid_from", v["valid_from"]))
            return Plan("insert", issues=issues, context=context)
        context["supersede_from"] = starts.isoformat()
        return Plan("update", item.id, item.version, {"unit_price": [jsonable(item.unit_price), v["unit_price"]]}, issues,
                    context)

    def apply(self, uow: UnitOfWork, prepared: Prepared, plan: Plan, options: Mapping[str, Any]) -> list[Change]:
        from app.modules.pricing import service as pricing
        from app.modules.pricing.schemas import PriceListCreate, PriceListItemCreate, SupersedeItem

        v = prepared.values
        ctx = plan.context
        job_ref = f"import:{options.get('job_id', '')}"[:200]
        changes: list[Change] = []
        if plan.action == "update":
            new = pricing.supersede_item(
                uow, plan.target_id,  # type: ignore[arg-type]
                SupersedeItem(unit_price=Decimal(v["unit_price"]), valid_from=date.fromisoformat(ctx["supersede_from"]),
                              reason=f"import {options.get('job_id', '')}"),
            )
            return [Change("pricing_price_list_item", new.id, "insert", None, {"unit_price": v["unit_price"]},
                           ["unit_price"], None)]
        price_list = pricing.find_price_list(uow, ctx["list_code"])
        if price_list is None:
            price_list = pricing.create_price_list(
                uow,
                PriceListCreate(
                    code=ctx["list_code"], name=f"Standard {v['price_type']} {v['currency']}",
                    price_type=v["price_type"], currency=v["currency"], default_unit_code=ctx["unit"],
                    valid_from=date.fromisoformat(v["valid_from"]) if v["valid_from"] else pricing.business_date(uow),
                    source_kind="import", source_ref=job_ref,
                ),
                origin="import",
            )
            changes.append(Change("pricing_price_list", price_list.id, "insert", None, {"code": price_list.code},
                                  ["code"], price_list.version))
        item = pricing.add_item(
            uow,
            price_list.id,
            PriceListItemCreate(
                product_id=ctx["product_id"], unit_code=ctx["unit"], unit_price=Decimal(v["unit_price"]),
                final_price=Decimal(v["unit_price"]),
                base_price=Decimal(v["base_price"]) if v["base_price"] else None,
                base_price_label=v["base_price_label"],
                addon_price=Decimal(v["addon_price"]) if v["addon_price"] else None,
                addon_price_label=v["addon_price_label"], price_basis=v["price_basis"],
                yield_qty_per_board=Decimal(v["yield_qty_per_board"]) if v["yield_qty_per_board"] else None,
                thickness_mm=Decimal(v["thickness_mm"]) if v["thickness_mm"] else None,
                moq=Decimal(v["moq"]) if v["moq"] else None, moq_unit_code=ctx["unit"] if v["moq"] else None,
                notes=v["price_notes"],
                valid_from=date.fromisoformat(v["valid_from"]) if v["valid_from"] else None,
                valid_to=date.fromisoformat(v["valid_to"]) if v["valid_to"] else None,
                source_kind="import", source_ref=job_ref, source_sheet=v["source_sheet"],
                source_row=(v["source_row"] or "")[:40] or None,
            ),
        )
        changes.append(Change("pricing_price_list_item", item.id, "insert", None, {"unit_price": v["unit_price"]},
                              ["unit_price"], item.version))
        return changes
