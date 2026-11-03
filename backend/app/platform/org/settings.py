"""Typed settings: the ``SettingDef`` contract and the built-in org definitions.

A module contributes ``SettingDef``s through ``ModuleManifest.settings``; ``app.platform.org.service`` is the
only reader and writer. Each definition names a Pydantic value model (validated on every write), a scope
(company or branch), the permission keys to read and to manage it, and a default. Restricted sub-fields are
annotated with ``Restricted(guard_key)`` from the field-guard registry (``app/platform/authz/redaction.py``):
they are nulled for actors without the guard key, listed in ``redacted_fields``, never sent to a model, and
writing a definition that has restricted fields also requires every guard key. Secrets never live here.
"""

from __future__ import annotations

import re
import types
import typing
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, get_args, get_origin

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core.errors import ValidationFailed
from app.core.logging import register_restricted_log_fields
from app.core.money import CurrencyCode
from app.platform.authz.redaction import Restricted

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

SettingScope = Literal["company", "branch"]
_KEY = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


@dataclass(frozen=True)
class SettingDef:
    key: str
    model: type[BaseModel]
    description: str
    read_permission: str
    manage_permission: str
    scope: SettingScope = "company"
    #: a value instance, or a callable building it from the unit of work (e.g. names from the company row);
    #: None means ``model()`` (every field has a default)
    default: BaseModel | Callable[[UnitOfWork], BaseModel] | None = None
    #: cross-setting checks run on write (e.g. the default brand must exist in ``brands``). They run while the
    #: company's setting-validation lock is held, so two coupled settings are never validated against each
    #: other's stale values; both sides of an invariant need a hook.
    validate: Callable[[UnitOfWork, BaseModel], None] | None = None
    owner_module: str = "org"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not _KEY.match(self.key):
            raise ValueError(f"setting key {self.key!r} must be snake_case (^[a-z][a-z0-9_]{{1,63}}$)")
        # conventions §12: restricted field names never reach the logs (the structlog processor drops them)
        register_restricted_log_fields(restricted_log_names(self.model))

    def default_value(self, uow: UnitOfWork) -> BaseModel:
        if self.default is None:
            return self.model()
        if isinstance(self.default, BaseModel):
            return self.default.model_copy(deep=True)
        return self.default(uow)

    @property
    def guard_keys(self) -> frozenset[str]:
        return frozenset(r.guard for r in restricted_guards(self.model).values())


# ---- restricted-field discovery (nested models and lists of models) ---------------------------------------
def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    origin = get_origin(annotation)
    if origin in (list, tuple, set, frozenset, typing.Union, types.UnionType) or origin is Annotated:
        for arg in get_args(annotation):
            found.extend(_nested_models(arg))
    return found


def restricted_guards(model: type[BaseModel], prefix: str = "") -> dict[str, Restricted]:
    """Dotted field paths of every ``Restricted`` field in ``model`` (``[]`` marks list items)."""
    out: dict[str, Restricted] = {}
    for name, info in model.model_fields.items():
        path = f"{prefix}{name}"
        for meta in info.metadata:
            if isinstance(meta, Restricted):
                out[path] = meta
        for nested in _nested_models(info.annotation):
            is_list = get_origin(info.annotation) in (list, tuple) or any(
                get_origin(a) in (list, tuple) for a in get_args(info.annotation)
            )
            out.update(restricted_guards(nested, f"{path}[]." if is_list else f"{path}."))
    return out


def restricted_log_names(model: type[BaseModel]) -> set[str]:
    """Leaf names of the ``Restricted(log="drop")`` fields of ``model`` (the log processor matches key names)."""
    return {path.rsplit(".", 1)[-1] for path, meta in restricted_guards(model).items() if meta.log == "drop"}


# ---- value helpers ---------------------------------------------------------------------------------------
def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _upper_or_none(value: Any) -> Any:
    value = _blank_to_none(value)
    return value.upper().replace(" ", "") if isinstance(value, str) else value


def _opt_text(max_length: int, pattern: str | None = None) -> Any:
    """Optional text: blank becomes None; the length/pattern constraints apply to the text only."""
    text = Annotated[str, StringConstraints(max_length=max_length, pattern=pattern)]
    return Annotated[text | None, BeforeValidator(_blank_to_none)]


def _opt_code(pattern: str, max_length: int = 40) -> Any:
    """Optional identifier code: blank becomes None, upper-cased with spaces removed, then pattern-checked."""
    text = Annotated[str, StringConstraints(max_length=max_length, pattern=pattern)]
    return Annotated[text | None, BeforeValidator(_upper_or_none)]


GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
PAN_PATTERN = r"^[A-Z]{5}[0-9]{4}[A-Z]$"
IEC_PATTERN = r"^[A-Z0-9]{10}$"
IFSC_PATTERN = r"^[A-Z]{4}0[A-Z0-9]{6}$"
SWIFT_PATTERN = r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$"
ACCOUNT_NUMBER_PATTERN = r"^[A-Z0-9]{6,34}$"
EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,63}$"
PHONE_PATTERN = r"^\+?[0-9][0-9 ()\-]{5,24}$"
WEBSITE_PATTERN = r"^https?://[^\s]{3,200}$"


Name120 = _opt_text(120)
Name200 = _opt_text(200)
Email = _opt_text(254, EMAIL_PATTERN)
Phone = _opt_text(25, PHONE_PATTERN)
Website = _opt_text(210, WEBSITE_PATTERN)
Gstin = _opt_code(GSTIN_PATTERN)
Pan = _opt_code(PAN_PATTERN)
Iec = _opt_code(IEC_PATTERN)
Ifsc = _opt_code(IFSC_PATTERN)
SwiftBic = _opt_code(SWIFT_PATTERN)
AccountNumber = _opt_code(ACCOUNT_NUMBER_PATTERN)
TermsText = _opt_text(8000)
FooterText = _opt_text(1000)


class _Value(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---- company_identity -------------------------------------------------------------------------------------
class CompanyContacts(_Value):
    email: Email = None
    phone: Phone = None
    website: Website = None


class CompanyIdentity(_Value):
    """Printed on documents. Absent values are reported as not configured, never invented."""

    legal_name: Name200 = None
    display_name: Name120 = None
    address_lines: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=6)
    gstin: Gstin = None
    pan: Pan = None
    iec: Iec = None
    contacts: CompanyContacts = Field(default_factory=CompanyContacts)
    logo_file_id: uuid.UUID | None = None

    @field_validator("address_lines", mode="before")
    @classmethod
    def _drop_blank_lines(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [v.strip() for v in value if isinstance(v, str) and v.strip()] + [
                v for v in value if not isinstance(v, str)
            ]
        return value


def _company_identity_default(uow: UnitOfWork) -> CompanyIdentity:
    from app.platform.org.models import Company

    company = uow.session.get(Company, uow.actor.company_id) if uow.actor.company_id else None
    if company is None:
        return CompanyIdentity()
    return CompanyIdentity(legal_name=company.legal_name, display_name=company.display_name)


def _validate_company_identity(uow: UnitOfWork, value: BaseModel) -> None:
    assert isinstance(value, CompanyIdentity)
    if value.logo_file_id is not None:
        from app.platform.files.service import require_logo_image

        require_logo_image(uow, value.logo_file_id)


# ---- bank_details -----------------------------------------------------------------------------------------
BANK_GUARD = "org.bank_account.read"


class BankAccount(_Value):
    label: Annotated[str, Field(min_length=1, max_length=80)]
    account_name: Name120 = None
    bank_name: Annotated[str, Field(min_length=1, max_length=120)]
    branch_name: Name120 = None
    #: the full number is a restricted field (permissions.md §5): others see only the last four digits
    account_number: Annotated[AccountNumber, Restricted(BANK_GUARD, model_exposure="deny")] = None
    #: derived on every validation from ``account_number``; client input is ignored
    account_number_last4: str | None = None
    ifsc: Ifsc = None
    swift_bic: SwiftBic = None
    currency: CurrencyCode | None = None
    is_default: bool = False

    @model_validator(mode="after")
    def _derive_last4(self) -> BankAccount:
        self.account_number_last4 = self.account_number[-4:] if self.account_number else None
        return self


class BankDetails(_Value):
    accounts: list[BankAccount] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _one_default(self) -> BankDetails:
        if sum(1 for a in self.accounts if a.is_default) > 1:
            raise ValueError("only one bank account can be the default")
        labels = [a.label.casefold() for a in self.accounts]
        if len(labels) != len(set(labels)):
            raise ValueError("bank account labels must be unique")
        return self


# ---- document_terms ---------------------------------------------------------------------------------------
class DocumentTerms(_Value):
    quote: TermsText = None
    challan: TermsText = None
    footer: FooterText = None


# ---- brands -----------------------------------------------------------------------------------------------
class Brand(_Value):
    token: Annotated[str, Field(pattern=r"^[A-Z]{2,4}$")]
    name: Annotated[str, Field(min_length=1, max_length=80)]


#: built-in brands (fixtures.md §2): token -> name; the token appears in document numbers ({brand}-QT-...)
DEFAULT_BRANDS: tuple[tuple[str, str], ...] = (("LK", "Lamikraft"), ("CR", "Crown"))


def _default_brands() -> list[Brand]:
    return [Brand.model_validate({"token": token, "name": name}) for token, name in DEFAULT_BRANDS]


class Brands(_Value):
    brands: list[Brand] = Field(default_factory=_default_brands, min_length=1, max_length=20)

    @model_validator(mode="after")
    def _unique_tokens(self) -> Brands:
        tokens = [b.token for b in self.brands]
        if len(tokens) != len(set(tokens)):
            raise ValueError("brand tokens must be unique")
        return self

    def tokens(self) -> set[str]:
        return {b.token for b in self.brands}


# ---- quote_defaults ---------------------------------------------------------------------------------------
Incoterm = Literal["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]
PriceType = Literal["export", "domestic", "sample", "distributor"]


class QuoteDefaults(_Value):
    currency: CurrencyCode = "EUR"
    incoterm: Incoterm = "FOB"
    validity_days: int = Field(default=30, ge=1, le=365)
    brand: Annotated[str, Field(pattern=r"^[A-Z]{2,4}$")] = "LK"
    price_type: PriceType = "export"
    #: a duplicated quote is assigned to the person who duplicates it (legacy policy)
    duplicate_copies_assignee: bool = True


def _validate_quote_defaults(uow: UnitOfWork, value: BaseModel) -> None:
    assert isinstance(value, QuoteDefaults)
    from app.platform.org.service import stored_or_default

    brands = stored_or_default(uow, "brands")
    assert isinstance(brands, Brands)
    if value.brand not in brands.tokens():
        raise ValidationFailed(
            "The default brand must be one of the configured brands.",
            code="validation_failed",
            errors=[{"loc": ["body", "value", "brand"], "msg": "unknown brand token", "code": "unknown_brand"}],
        )


def _validate_brands(uow: UnitOfWork, value: BaseModel) -> None:
    assert isinstance(value, Brands)
    from app.platform.org.service import stored_or_default

    defaults = stored_or_default(uow, "quote_defaults")
    assert isinstance(defaults, QuoteDefaults)
    if defaults.brand not in value.tokens():
        raise ValidationFailed(
            "This brand is the default for new quotes; change the quote defaults first.",
            code="validation_failed",
            errors=[{"loc": ["body", "value", "brands"], "msg": "brand in use by quote_defaults", "code": "brand_in_use"}],
        )


# ---- security_policy (identity reads it at sign-in) ----------------------------------------------------------
class SecurityPolicy(_Value):
    #: privileged: members holding identity/org/audit/system administration keys must use MFA at sign-in;
    #: all: every member must
    mfa_required_for: Literal["privileged", "all"] = "privileged"


def read_security_policy(uow: UnitOfWork) -> SecurityPolicy:
    """The company's security policy (unredacted; no restricted fields)."""
    from app.platform.org.service import stored_or_default

    value = stored_or_default(uow, "security_policy")
    assert isinstance(value, SecurityPolicy)  # noqa: S101 - the registered model
    return value


BUILTIN_SETTINGS: tuple[SettingDef, ...] = (
    SettingDef(
        key="company_identity",
        model=CompanyIdentity,
        description="Legal and display name, address, GSTIN, PAN, IEC, contacts and logo printed on documents",
        read_permission="org.settings.read",
        manage_permission="org.company.update",
        default=_company_identity_default,
        validate=_validate_company_identity,
    ),
    SettingDef(
        key="bank_details",
        model=BankDetails,
        description="Company bank accounts printed on documents (account numbers are restricted)",
        read_permission="org.settings.read",
        manage_permission="org.bank_account.update",
    ),
    SettingDef(
        key="document_terms",
        model=DocumentTerms,
        description="Terms printed on quotes and delivery challans, and the document footer",
        read_permission="org.settings.read",
        manage_permission="org.settings.manage",
    ),
    SettingDef(
        key="quote_defaults",
        model=QuoteDefaults,
        description="Defaults for new quotes: currency, incoterm, validity, brand, price type, duplicate assignee",
        read_permission="org.settings.read",
        manage_permission="sales.quote_settings.manage",
        validate=_validate_quote_defaults,
    ),
    SettingDef(
        key="brands",
        model=Brands,
        description="Brand tokens used in document numbers and headers",
        read_permission="org.settings.read",
        manage_permission="org.settings.manage",
        validate=_validate_brands,
    ),
    SettingDef(
        key="security_policy",
        model=SecurityPolicy,
        description="Who must use two-step sign-in (authenticator app): administrators only, or everyone",
        read_permission="org.settings.read",
        manage_permission="identity.mfa.manage",
    ),
)
