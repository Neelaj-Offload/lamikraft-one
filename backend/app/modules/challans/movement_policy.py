"""Which type / return type / destination combinations are valid (docs/design/source/operations.md §4).

Slice 2 records documents only (``inventory_effect = none``); Slice 4 attaches the stock movement of each row of the
policy matrix. The matrix is enforced on every save (422 with field locations) so a draft never holds a combination
that cannot be issued; ``issue`` re-checks it together with the destination requirements.

| Type | Return types | Destinations |
|---|---|---|
| Outward | either | Customer, Fabricator, Vendor, Transporter |
| Inward | non-returnable | any except Warehouse |
| Return | either (inherits the original) | Customer, Fabricator, Vendor, Transporter, Office |
| Job Work | returnable (forced) | Fabricator, Vendor |
| Transfer | non-returnable | Warehouse, Office |
| Sample | either | any except Warehouse |
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.challans.schemas import ChallanType, DestinationType, ReturnType

T = ChallanType
R = ReturnType
Dt = DestinationType
_ALL = frozenset(DestinationType)


@dataclass(frozen=True)
class Rule:
    return_types: frozenset[ReturnType]
    destinations: frozenset[DestinationType]
    #: the return type applied when the caller does not choose one
    default_return: ReturnType
    #: ``True`` when the type is always returnable (Job Work: the material stays company-owned)
    forced_returnable: bool = False


POLICY: dict[ChallanType, Rule] = {
    T.OUTWARD: Rule(
        frozenset(R), frozenset({Dt.CUSTOMER, Dt.FABRICATOR, Dt.VENDOR, Dt.TRANSPORTER}), R.NON_RETURNABLE
    ),
    T.INWARD: Rule(frozenset({R.NON_RETURNABLE}), _ALL - {Dt.WAREHOUSE}, R.NON_RETURNABLE),
    T.RETURN: Rule(
        frozenset(R),
        frozenset({Dt.CUSTOMER, Dt.FABRICATOR, Dt.VENDOR, Dt.TRANSPORTER, Dt.OFFICE}),
        R.NON_RETURNABLE,
    ),
    T.JOB_WORK: Rule(
        frozenset({R.RETURNABLE}), frozenset({Dt.FABRICATOR, Dt.VENDOR}), R.RETURNABLE, forced_returnable=True
    ),
    T.TRANSFER: Rule(frozenset({R.NON_RETURNABLE}), frozenset({Dt.WAREHOUSE, Dt.OFFICE}), R.NON_RETURNABLE),
    T.SAMPLE: Rule(frozenset(R), _ALL - {Dt.WAREHOUSE}, R.RETURNABLE),
}

#: party roles accepted for a linked destination party, per destination type (None: any role)
PARTY_ROLES: dict[DestinationType, frozenset[str] | None] = {
    Dt.CUSTOMER: frozenset({"customer"}),
    Dt.FABRICATOR: frozenset({"fabricator", "job_worker"}),
    Dt.VENDOR: frozenset({"vendor"}),
    Dt.TRANSPORTER: None,
}

#: destinations that are company locations, not parties
LOCATION_DESTINATIONS = frozenset({Dt.WAREHOUSE, Dt.OFFICE})


@dataclass(frozen=True)
class Problem:
    field: str
    code: str
    message: str


def default_return_type(challan_type: ChallanType) -> ReturnType:
    return POLICY[challan_type].default_return


def check_combination(
    challan_type: ChallanType, return_type: ReturnType, destination_type: DestinationType
) -> list[Problem]:
    """Problems with the type / return type / destination combination (empty when valid)."""
    rule = POLICY[challan_type]
    problems: list[Problem] = []
    if return_type not in rule.return_types:
        if rule.forced_returnable:
            problems.append(
                Problem(
                    "return_type", "job_work_must_be_returnable", "Job Work challans are always returnable"
                )
            )
        else:
            allowed = ", ".join(sorted(r.value for r in rule.return_types))
            problems.append(
                Problem(
                    "return_type", "return_type_not_allowed", f"{challan_type.value} challans are {allowed}"
                )
            )
    if destination_type not in rule.destinations:
        allowed = ", ".join(sorted(d.value for d in rule.destinations))
        problems.append(
            Problem(
                "destination_type",
                "destination_not_allowed",
                f"{challan_type.value} challans go to {allowed}",
            )
        )
    return problems


def party_role_ok(destination_type: DestinationType, roles: list[str] | tuple[str, ...]) -> bool:
    wanted = PARTY_ROLES.get(destination_type)
    return wanted is None or bool(wanted & set(roles))


def direction(challan_type: ChallanType) -> str:
    """Goods come in on Inward and Return challans; every other type sends them out."""
    return "inward" if challan_type in (T.INWARD, T.RETURN) else "outward"
