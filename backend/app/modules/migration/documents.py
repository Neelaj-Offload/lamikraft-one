"""Dry-run analysers for the legacy documents and people: users, quote settings, custom products, quotes with their
lines and revisions, grain locks, delivery challans with lines, and opening balances.

Rules (OPUS build prompt ``<migration>``):
- issued quotes are kept exactly as exported; legacy totals are recomputed only to report discrepancies
  (``LEGACY_TOTAL_DISCREPANCY``, ``LINE_TOTAL_DISCREPANCY``, ``LINE_COUNT_MISMATCH``) and never rewritten;
- duplicate identities (same id or document number with different content) are quarantined;
- users become invitation candidates (active) or historical attribution (inactive); credentials are never read
  into the new system (``CREDENTIAL_DROPPED``); legacy roles and overrides map through the permission alias table;
- legacy challans are documents only: no stock movement is planned from them (``stock_movements`` = 0);
- opening balances (an authorised count, not a legacy collection) are staged as a separate batch.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select

from app.modules.imports.definitions.base import Issue
from app.modules.migration.analysis import (
    ACCEPTED,
    ERROR,
    INFO,
    QUARANTINE,
    WARNING,
    Analysis,
    field_text,
    fold_key,
    group_duplicates,
)
from app.modules.migration.sources import SourceRow

QUOTE_STATUSES = ("draft", "internal_review", "sent", "revised", "won", "lost", "cancelled", "archived")
CHALLAN_STATUSES = ("draft", "issued", "closed", "cancelled")
LEGACY_ROLES = {"admin": "admin", "management": "management", "sales": "sales", "operations": "operations"}
CURRENCIES = ("INR", "EUR", "USD", "GBP")
LINE_TYPES = ("catalog", "custom", "manual")
CENT = Decimal("0.01")
_CHALLAN_NUMBER = re.compile(r"^DC-\d{4}-\d{4,}$")
_CUSTOM_CODE = re.compile(r"^CP-\d{4,}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def money(
    values: dict[str, Any], name: str, issues: list[Issue], *, required: bool = False
) -> Decimal | None:
    raw = field_text(values, name)
    if raw is None:
        if required:
            issues.append(Issue("REQUIRED", ERROR, f"{name} is required", name))
        return None
    clean = raw.replace(",", "").replace("€", "").replace("₹", "").replace("$", "").replace("£", "").strip()
    try:
        d = Decimal(clean)
    except InvalidOperation:
        issues.append(Issue("NOT_A_NUMBER", ERROR, f"{name} must be a number", name, raw))
        return None
    if not d.is_finite():
        issues.append(Issue("NOT_A_NUMBER", ERROR, f"{name} must be a number", name, raw))
        return None
    return d


def cents(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def _snapshot(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _settle_grouped(
    an: Analysis,
    entity: str,
    rows: list[SourceRow],
    key_of: Any,
    check: Any,
    business_of: Any = None,
    code: str = "DUPLICATE_IDENTITY",
) -> None:
    unique, conflicts, repeats = group_duplicates(rows, key_of)
    for key, group in conflicts.items():
        for row in group:
            issues = check(row)
            issues.append(
                Issue(
                    code,
                    QUARANTINE,
                    f"{len(group)} rows share {key} with different values; none is "
                    "migrated until one is chosen",
                    None,
                    key,
                )
            )
            an.settle(row, entity, key, issues, business_key=business_of(row) if business_of else key)
    for row, key in repeats:
        an.duplicate(row, entity, key)
    for row, key in unique:
        an.settle(row, entity, key, check(row), business_key=business_of(row) if business_of and key else key)


def _number_clash(
    an: Analysis, entity: str, rows: list[SourceRow], number_field: str
) -> dict[str, list[str]]:
    """Document numbers shared by different ids (duplicate identities across ids)."""
    ids_by_number: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        number, ident = field_text(row.values, number_field), field_text(row.values, "id", "_id")
        if number and ident:
            ids_by_number[fold_key(number)].add(ident)
    return {n: sorted(ids) for n, ids in ids_by_number.items() if len(ids) > 1}


# ---- users ---------------------------------------------------------------------------------------------------------
def analyse_users(an: Analysis) -> None:
    from app.platform.identity.models import AppUser, Membership
    from app.registry import get_registry

    rows = an.source.rows("users")
    if not rows:
        return
    aliases = get_registry().legacy_alias_map()
    members = {
        e.casefold()
        for e in an.uow.session.scalars(
            select(AppUser.email_normalized)
            .join(Membership, Membership.user_id == AppUser.id)
            .where(Membership.company_id == an.uow.actor.company_id)
        )
    }
    emails: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        email, ident = field_text(row.values, "email"), field_text(row.values, "id", "_id")
        if email and ident:
            emails[email.casefold()].add(ident)
    shared_email = {e for e, ids in emails.items() if len(ids) > 1}
    summary: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []

    def check(row: SourceRow) -> list[Issue]:
        v = row.values
        issues: list[Issue] = []
        email = field_text(v, "email")
        if not email:
            issues.append(Issue("REQUIRED", ERROR, "email is required", "email"))
        elif not _EMAIL.match(email):
            issues.append(Issue("EMAIL_FORMAT", ERROR, "email is not a valid address", "email", email))
        elif email.casefold() in shared_email:
            issues.append(
                Issue(
                    "DUPLICATE_IDENTITY",
                    QUARANTINE,
                    f"{email} belongs to more than one legacy user",
                    "email",
                    email,
                )
            )
        role = (field_text(v, "role") or "").casefold()
        if role not in LEGACY_ROLES:
            issues.append(
                Issue(
                    "ROLE_UNKNOWN",
                    QUARANTINE,
                    f"role '{role or '(blank)'}' is not a legacy role",
                    "role",
                    role or None,
                )
            )
        if any(k in v for k in ("password_hash", "hashed_password", "password")):
            issues.append(
                Issue(
                    "CREDENTIAL_DROPPED",
                    INFO,
                    "The legacy password hash is not migrated; the person sets "
                    "a new password through an invitation",
                    "password_hash",
                )
            )
        overrides = _snapshot(v.get("permission_overrides")) or {}
        if isinstance(overrides, dict):
            for legacy in [*(overrides.get("grant") or []), *(overrides.get("revoke") or [])]:
                if str(legacy) not in aliases:
                    issues.append(
                        Issue(
                            "OVERRIDE_UNKNOWN",
                            WARNING,
                            f"legacy permission '{legacy}' has no new key",
                            "permission_overrides",
                            str(legacy),
                        )
                    )
        return issues

    def business(row: SourceRow) -> str | None:
        email = field_text(row.values, "email")
        return email.casefold() if email else None

    _settle_grouped(an, "users", rows, lambda r: field_text(r.values, "id", "_id"), check, business)
    for key, acc in an.accepted["users"].items():
        v = acc.row.values
        email = (field_text(v, "email") or "").casefold()
        active = str(field_text(v, "is_active") or "true").casefold() in ("true", "1", "yes", "active")
        overrides = _snapshot(v.get("permission_overrides")) or {}
        grant = (
            sorted({k for p in (overrides.get("grant") or []) for k in aliases.get(str(p), [])})
            if isinstance(overrides, dict)
            else []
        )
        revoke = (
            sorted({k for p in (overrides.get("revoke") or []) for k in aliases.get(str(p), [])})
            if isinstance(overrides, dict)
            else []
        )
        kind = "existing_member" if email in members else "invitation" if active else "historical"
        summary[kind] += 1
        candidates.append(
            {
                "source_key": key,
                "email": email,
                "name": field_text(v, "name") or email,
                "kind": kind,
                "role_template": LEGACY_ROLES.get((field_text(v, "role") or "").casefold()),
                "grant": grant,
                "revoke": revoke,
                "last_login": field_text(v, "last_login"),
            }
        )
    summary["credentials_dropped"] = sum(
        1 for f in an.findings if f.entity == "users" and f.code == "CREDENTIAL_DROPPED"
    )
    an.report["users"] = {**dict(summary), "candidates": sorted(candidates, key=lambda c: c["email"])}


def user_names(an: Analysis) -> dict[str, str]:
    """legacy user id -> name (every user in the export, accepted or not: attribution survives quarantine)."""
    return {
        field_text(r.values, "id", "_id") or "": field_text(r.values, "name") or field_text(r.values, "email") or ""
        for r in an.source.rows("users")
    }


def _attribution(an: Analysis, row: SourceRow, entity: str, key: str, names: dict[str, str]) -> None:
    counts = an.report.setdefault("attribution", {"resolved": 0, "name_only": 0, "unresolved": 0})
    for id_field, name_field in (
        ("created_by", "created_by_name"),
        ("assigned_to", "assigned_to_name"),
        ("updated_by", None),
    ):
        ident = field_text(row.values, id_field)
        name = field_text(row.values, name_field) if name_field else None
        if not ident and not name:
            continue
        if ident and ident in names:
            counts["resolved"] += 1
        elif name:
            counts["name_only"] += 1
            an.add(
                row,
                entity,
                "ATTRIBUTION_NAME_ONLY",
                INFO,
                f"{id_field} {ident or '(blank)'} is not a legacy user; "
                f"the name '{name}' is kept as historical attribution",
                key=key,
                field_name=id_field,
                with_raw=False,
            )
        else:
            counts["unresolved"] += 1
            an.add(
                row,
                entity,
                "ATTRIBUTION_UNRESOLVED",
                WARNING,
                f"{id_field} {ident} is not a legacy user and has no name",
                key=key,
                field_name=id_field,
                raw_value=ident,
                with_raw=False,
            )


# ---- quote settings, grain locks -------------------------------------------------------------------------------------
def analyse_quote_settings(an: Analysis) -> None:
    rows = an.source.rows("quote_settings")
    for i, row in enumerate(rows):
        issues: list[Issue] = []
        if i > 0:
            issues.append(
                Issue(
                    "SINGLETON_REPEATED",
                    QUARANTINE,
                    "quote_settings is a singleton; only one row is expected",
                    None,
                )
            )
        an.settle(row, "quote_settings", "quote_settings" if i == 0 else f"quote_settings#{i + 1}", issues)
        if i == 0:
            an.report["quote_settings"] = {
                k: field_text(row.values, k)
                for k in ("brand_prefix", "quote_prefix", "year_format", "next_sequence")
            }


def analyse_grain_locks(an: Analysis) -> None:
    from app.modules.catalogue.normalise import normalise_identifier

    rows = an.source.rows("grain_locked_decors")

    def key_of(row: SourceRow) -> str | None:
        raw = field_text(row.values, "decor", "decor_no")
        return normalise_identifier(raw, float_artefact_rule=True).value if raw else None

    def check(row: SourceRow) -> list[Issue]:
        raw = field_text(row.values, "decor", "decor_no")
        if raw is None:
            return [Issue("REQUIRED", ERROR, "decor is required", "decor")]
        result = normalise_identifier(raw, float_artefact_rule=True)
        return [
            Issue(w, WARNING, f"decor '{raw}' read as '{result.value}'", "decor", raw)
            for w in result.warnings
        ]

    _settle_grouped(an, "grain_locked_decors", rows, key_of, check)


# ---- custom products -----------------------------------------------------------------------------------------------
def analyse_custom_products(an: Analysis, known_products: set[str]) -> None:
    rows = an.source.rows("custom_products")
    clash = _number_clash(an, "custom_products", rows, "custom_code")

    def check(row: SourceRow) -> list[Issue]:
        v = row.values
        issues: list[Issue] = []
        code = field_text(v, "custom_code")
        if not code:
            issues.append(Issue("REQUIRED", ERROR, "custom_code is required", "custom_code"))
        else:
            if not _CUSTOM_CODE.match(code):
                issues.append(
                    Issue(
                        "CODE_FORMAT",
                        WARNING,
                        f"custom_code '{code}' is not CP-NNNN; kept as is",
                        "custom_code",
                        code,
                    )
                )
            if fold_key(code) in clash:
                issues.append(
                    Issue(
                        "DUPLICATE_IDENTITY",
                        QUARANTINE,
                        f"{code} is used by legacy ids {', '.join(clash[fold_key(code)])}",
                        "custom_code",
                        code,
                    )
                )
        base = field_text(v, "base_product_key")
        if base and base not in known_products:
            issues.append(
                Issue(
                    "BASE_PRODUCT_UNRESOLVED",
                    WARNING,
                    f"base product {base} is not in the export or the catalogue; the key is kept as text",
                    "base_product_key",
                    base,
                )
            )
        money(v, "quoted_price", issues)
        return issues

    _settle_grouped(
        an,
        "custom_products",
        rows,
        lambda r: field_text(r.values, "id", "_id"),
        check,
        lambda r: field_text(r.values, "custom_code"),
    )


# ---- quotes, lines, revisions -----------------------------------------------------------------------------------------
def analyse_quotes(an: Analysis, known_products: set[str]) -> None:
    quotes = an.source.rows("quotes")
    lines = an.source.rows("quote_lines")
    revisions = an.source.rows("quote_revisions")
    if not (quotes or lines or revisions):
        return
    names = user_names(an)
    clash = _number_clash(an, "quotes", quotes, "quote_number")
    quote_ids = {field_text(r.values, "id", "_id") for r in quotes} - {None}
    custom_ids = {field_text(r.values, "id", "_id") for r in an.source.rows("custom_products")} - {None}

    # -- lines first: each quote's discrepancy check needs its lines
    lines_by_quote: dict[str, list[SourceRow]] = defaultdict(list)

    def line_check(row: SourceRow) -> list[Issue]:
        v = row.values
        issues: list[Issue] = []
        qid = field_text(v, "quote_id")
        if not qid:
            issues.append(Issue("REQUIRED", ERROR, "quote_id is required", "quote_id"))
        elif qid not in quote_ids:
            issues.append(
                Issue("ORPHAN_LINE", QUARANTINE, f"quote {qid} is not in the export", "quote_id", qid)
            )
        line_type = (field_text(v, "line_type") or "").casefold()
        if line_type not in LINE_TYPES:
            issues.append(
                Issue(
                    "LINE_TYPE_UNKNOWN",
                    QUARANTINE,
                    f"line_type '{line_type or '(blank)'}' is not catalog/custom/manual",
                    "line_type",
                    line_type or None,
                )
            )
        pk = field_text(v, "product_key")
        if line_type == "catalog" and pk and pk not in known_products:
            issues.append(
                Issue(
                    "LINE_PRODUCT_UNRESOLVED",
                    WARNING,
                    f"product {pk} is not in the export or the catalogue; the line snapshot is kept",
                    "product_key",
                    pk,
                )
            )
        cp = field_text(v, "custom_product_id")
        if line_type == "custom" and cp and cp not in custom_ids:
            issues.append(
                Issue(
                    "LINE_CUSTOM_UNRESOLVED",
                    WARNING,
                    f"custom product {cp} is not in the export; the line snapshot is kept",
                    "custom_product_id",
                    cp,
                )
            )
        qty = money(v, "quantity", issues, required=True)
        price = money(v, "quoted_price", issues, required=True)
        recorded = money(v, "line_total", issues)
        default = money(v, "default_price", issues)
        if (
            qty is not None
            and price is not None
            and recorded is not None
            and cents(qty * price) != cents(recorded)
        ):
            issues.append(
                Issue(
                    "LINE_TOTAL_DISCREPANCY",
                    WARNING,
                    f"line_total {recorded} differs from quantity x "
                    f"quoted_price = {cents(qty * price)}; the legacy value is kept",
                    "line_total",
                    str(recorded),
                )
            )
        if default is not None and price is not None and price != default and not field_text(v, "override_reason"):
            issues.append(
                Issue(
                    "OVERRIDE_WITHOUT_REASON",
                    INFO,
                    "quoted_price differs from default_price with no reason (historical; kept)",
                    "override_reason",
                )
            )
        return issues

    _settle_grouped(an, "quote_lines", lines, lambda r: field_text(r.values, "id", "_id"), line_check)
    for acc in an.accepted["quote_lines"].values():
        qid = field_text(acc.row.values, "quote_id")
        if qid:
            lines_by_quote[qid].append(acc.row)

    totals: dict[str, dict[str, Decimal | int]] = defaultdict(lambda: defaultdict(Decimal))  # type: ignore[arg-type]
    discrepancies: list[dict[str, Any]] = []
    # source totals over every parseable quote (accepted or not), for the reconciliation report
    for row in quotes:
        cur = (field_text(row.values, "currency") or "").upper() or "(blank)"
        total = money(row.values, "total_amount", [])
        totals[cur]["source_quotes"] += 1
        if total is not None:
            totals[cur]["source_total"] += total

    def quote_check(row: SourceRow) -> list[Issue]:
        v = row.values
        issues: list[Issue] = []
        number = field_text(v, "quote_number")
        if not number:
            issues.append(Issue("REQUIRED", ERROR, "quote_number is required", "quote_number"))
        elif fold_key(number) in clash:
            issues.append(
                Issue(
                    "DUPLICATE_IDENTITY",
                    QUARANTINE,
                    f"{number} is used by legacy ids {', '.join(clash[fold_key(number)])}",
                    "quote_number",
                    number,
                )
            )
        status = (field_text(v, "status") or "").casefold()
        if status not in QUOTE_STATUSES:
            issues.append(
                Issue(
                    "STATUS_UNKNOWN",
                    QUARANTINE,
                    f"status '{status or '(blank)'}' is not a quote status",
                    "status",
                    status or None,
                )
            )
        currency = (field_text(v, "currency") or "").upper()
        if not currency:
            issues.append(
                Issue(
                    "CURRENCY_MISSING",
                    QUARANTINE,
                    "currency is blank on an issued document (no default is assumed)",
                    "currency",
                )
            )
        elif currency not in CURRENCIES:
            issues.append(
                Issue(
                    "CURRENCY_UNKNOWN",
                    QUARANTINE,
                    f"currency '{currency}' is not enabled",
                    "currency",
                    currency,
                )
            )
        money(v, "total_amount", issues)
        if not field_text(v, "customer_name"):
            issues.append(
                Issue(
                    "CUSTOMER_MISSING", WARNING, "customer_name is blank; no party candidate", "customer_name"
                )
            )
        return issues

    _settle_grouped(
        an,
        "quotes",
        quotes,
        lambda r: field_text(r.values, "id", "_id"),
        quote_check,
        lambda r: field_text(r.values, "quote_number"),
    )
    for key, acc in an.accepted["quotes"].items():
        v = acc.row.values
        cur = (field_text(v, "currency") or "").upper()
        legacy = money(v, "total_amount", []) or Decimal(0)
        own = lines_by_quote.get(key, [])
        recorded_lines = sum((money(r.values, "line_total", []) or Decimal(0) for r in own), Decimal(0))
        recomputed = sum(
            (
                cents(
                    (money(r.values, "quantity", []) or Decimal(0))
                    * (money(r.values, "quoted_price", []) or Decimal(0))
                )
                for r in own
            ),
            Decimal(0),
        )
        t = totals[cur]
        t["accepted_quotes"] += 1
        t["accepted_total"] += legacy
        t["recorded_lines_total"] += recorded_lines
        t["recomputed_total"] += recomputed
        acc.values = {**acc.values, "_lines_total": str(recorded_lines), "_recomputed_total": str(recomputed)}
        declared = field_text(v, "total_lines")
        if declared is not None and declared.isdigit() and int(declared) != len(own):
            an.add(
                acc.row,
                "quotes",
                "LINE_COUNT_MISMATCH",
                WARNING,
                f"total_lines says {declared}; the export holds {len(own)} migratable lines",
                key=key,
                field_name="total_lines",
                raw_value=declared,
            )
        if cents(legacy) != cents(recomputed):
            t["discrepant_quotes"] += 1
            t["discrepancy_total"] += cents(legacy) - cents(recomputed)
            discrepancies.append(
                {
                    "source_key": key,
                    "quote_number": field_text(v, "quote_number"),
                    "currency": cur,
                    "legacy_total": str(cents(legacy)),
                    "lines_total": str(cents(recorded_lines)),
                    "recomputed_total": str(cents(recomputed)),
                    "difference": str(cents(legacy) - cents(recomputed)),
                }
            )
            an.add(
                acc.row,
                "quotes",
                "LEGACY_TOTAL_DISCREPANCY",
                WARNING,
                f"legacy total {cents(legacy)} {cur} differs from the lines ({cents(recomputed)}); the issued "
                "snapshot is kept exactly and the difference is reported",
                key=key,
                field_name="total_amount",
                raw_value=str(legacy),
            )
        _attribution(an, acc.row, "quotes", key, names)
    quoted_ids = set(an.accepted["quotes"])

    def revision_check(row: SourceRow) -> list[Issue]:
        v = row.values
        issues: list[Issue] = []
        qid = field_text(v, "quote_id")
        if not qid or qid not in quote_ids:
            issues.append(
                Issue(
                    "ORPHAN_REVISION",
                    QUARANTINE,
                    f"quote {qid or '(blank)'} is not in the export",
                    "quote_id",
                    qid,
                )
            )
        snap = _snapshot(v.get("snapshot"))
        if not isinstance(snap, dict):
            issues.append(Issue("SNAPSHOT_UNREADABLE", ERROR, "snapshot is not a JSON object", "snapshot"))
        version = field_text(v, "version")
        if version is not None and not version.isdigit():
            issues.append(Issue("NOT_INTEGER", ERROR, "version must be a whole number", "version", version))
        return issues

    _settle_grouped(an, "quote_revisions", revisions, lambda r: field_text(r.values, "id", "_id"), revision_check)
    an.report["quotes"] = {
        "totals_by_currency": {
            cur: {
                k: str(cents(x)) if isinstance(x, Decimal) and "total" in k else int(x)
                for k, x in sorted(t.items())
            }
            for cur, t in sorted(totals.items())
        },
        "discrepancies": discrepancies,
        "lines_linked": sum(len(v) for k, v in lines_by_quote.items() if k in quoted_ids),
    }


# ---- challans ------------------------------------------------------------------------------------------------------
def analyse_challans(an: Analysis, known_products: set[str]) -> None:
    challans = an.source.rows("delivery_challans")
    lines = an.source.rows("delivery_challan_lines")
    if not (challans or lines):
        return
    names = user_names(an)
    clash = _number_clash(an, "delivery_challans", challans, "challan_number")
    challan_ids = {field_text(r.values, "id", "_id") for r in challans} - {None}

    def check(row: SourceRow) -> list[Issue]:
        v = row.values
        issues: list[Issue] = []
        number = field_text(v, "challan_number")
        if not number:
            issues.append(Issue("REQUIRED", ERROR, "challan_number is required", "challan_number"))
        else:
            if not _CHALLAN_NUMBER.match(number):
                issues.append(
                    Issue(
                        "NUMBER_FORMAT",
                        WARNING,
                        f"challan_number '{number}' is not DC-YYYY-NNNN; kept",
                        "challan_number",
                        number,
                    )
                )
            if fold_key(number) in clash:
                issues.append(
                    Issue(
                        "DUPLICATE_IDENTITY",
                        QUARANTINE,
                        f"{number} is used by legacy ids {', '.join(clash[fold_key(number)])}",
                        "challan_number",
                        number,
                    )
                )
        status = (field_text(v, "status") or "").casefold()
        if status and status not in CHALLAN_STATUSES:
            issues.append(
                Issue(
                    "STATUS_UNVALIDATED",
                    WARNING,
                    f"status '{status}' was never validated by the legacy system; kept as text",
                    "status",
                    status,
                )
            )
        return issues

    _settle_grouped(
        an,
        "delivery_challans",
        challans,
        lambda r: field_text(r.values, "id", "_id"),
        check,
        lambda r: field_text(r.values, "challan_number"),
    )
    for key, acc in an.accepted["delivery_challans"].items():
        _attribution(an, acc.row, "delivery_challans", key, names)

    def line_check(row: SourceRow) -> list[Issue]:
        v = row.values
        issues: list[Issue] = []
        cid = field_text(v, "challan_id")
        if not cid or cid not in challan_ids:
            issues.append(
                Issue(
                    "ORPHAN_LINE",
                    QUARANTINE,
                    f"challan {cid or '(blank)'} is not in the export",
                    "challan_id",
                    cid,
                )
            )
        money(v, "quantity", issues, required=True)
        code = field_text(v, "item_code")
        if (field_text(v, "line_type") or "").casefold() == "catalog" and code and code not in known_products:
            issues.append(
                Issue(
                    "ITEM_UNRESOLVED",
                    INFO,
                    f"item_code {code} is free text in the legacy challan (no product link); kept",
                    "item_code",
                    code,
                )
            )
        return issues

    _settle_grouped(an, "delivery_challan_lines", lines, lambda r: field_text(r.values, "id", "_id"), line_check)
    an.report["challans"] = {
        "documents": len(an.accepted["delivery_challans"]),
        "lines": len(an.accepted["delivery_challan_lines"]),
        "inventory_effect": "none",
        "stock_movements": 0,
    }


# ---- opening balances ------------------------------------------------------------------------------------------------
def analyse_opening_balances(an: Analysis, known_products: set[str]) -> None:
    rows = an.source.rows("opening_balances")
    if not rows:
        return

    def key_of(row: SourceRow) -> str | None:
        pk, loc = field_text(row.values, "product_key"), field_text(row.values, "location_code", "location", "warehouse")
        return f"{pk}|{loc}" if pk and loc else None

    def check(row: SourceRow) -> list[Issue]:
        v = row.values
        issues: list[Issue] = []
        pk = field_text(v, "product_key")
        if not pk:
            issues.append(Issue("REQUIRED", ERROR, "product_key is required", "product_key"))
        elif pk not in known_products:
            issues.append(
                Issue(
                    "ORPHAN_PRODUCT",
                    QUARANTINE,
                    f"product {pk} is neither in the export nor in the catalogue",
                    "product_key",
                    pk,
                )
            )
        if not field_text(v, "location_code", "location", "warehouse"):
            issues.append(Issue("REQUIRED", ERROR, "location_code is required", "location_code"))
        if not field_text(v, "uom", "uom_code", "unit"):
            issues.append(Issue("REQUIRED", ERROR, "uom is required (no unit is assumed)", "uom"))
        qty = money(v, "quantity", issues, required=True)
        if qty is not None and qty < 0:
            issues.append(
                Issue("NEGATIVE_QUANTITY", ERROR, "opening quantity cannot be negative", "quantity", str(qty))
            )
        money(v, "unit_cost", issues)
        return issues

    _settle_grouped(an, "opening_balances", rows, key_of, check, code="DUPLICATE_LOCATION")
    by_uom: dict[str, Decimal] = defaultdict(Decimal)
    for acc in an.accepted["opening_balances"].values():
        uom = (field_text(acc.row.values, "uom", "uom_code", "unit") or "").upper()
        by_uom[uom] += money(acc.row.values, "quantity", []) or Decimal(0)
    an.report["opening_balances"] = {
        "lines": len(an.accepted["opening_balances"]),
        "quantity_by_uom": {k: format(v.normalize(), "f") for k, v in sorted(by_uom.items())},
        "posting": "separate approved batch; posted by the inventory module",
    }


def known_products(an: Analysis) -> set[str]:
    from app.modules.catalogue.models import Product

    db = set(an.uow.session.scalars(select(Product.product_key)))
    return db | an.seen["products_master"]


def product_count(an: Analysis) -> int:
    from app.modules.catalogue.models import Product

    return int(an.uow.session.scalar(select(func.count()).select_from(Product)) or 0)


def analyse_documents(an: Analysis) -> None:
    known = known_products(an)
    analyse_users(an)
    analyse_quote_settings(an)
    analyse_custom_products(an, known)
    analyse_quotes(an, known)
    analyse_grain_locks(an)
    analyse_challans(an, known)
    analyse_opening_balances(an, known)


__all__ = ["ACCEPTED", "analyse_documents", "cents", "money", "user_names"]
