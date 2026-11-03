"""FG-DC-03: the movement policy matrix (type × return type × destination) and the party-role rule."""

from __future__ import annotations

import pytest

from app.modules.challans import movement_policy as mp
from app.modules.challans.schemas import ChallanType as T
from app.modules.challans.schemas import DestinationType as D
from app.modules.challans.schemas import ReturnType as R

RET, NON = R.RETURNABLE, R.NON_RETURNABLE


def test_policy_matrix_all_types_and_invalid_combinations() -> None:
    """Every type has a rule; the documented valid and invalid combinations come out as such (operations.md §4)."""
    assert set(mp.POLICY) == set(T)
    valid = [
        (T.OUTWARD, NON, D.CUSTOMER), (T.OUTWARD, RET, D.FABRICATOR), (T.OUTWARD, NON, D.TRANSPORTER), (T.OUTWARD, RET, D.VENDOR),
        (T.INWARD, NON, D.VENDOR), (T.INWARD, NON, D.CUSTOMER), (T.INWARD, NON, D.OFFICE),
        (T.RETURN, NON, D.CUSTOMER), (T.RETURN, RET, D.FABRICATOR), (T.RETURN, NON, D.OFFICE),
        (T.JOB_WORK, RET, D.FABRICATOR), (T.JOB_WORK, RET, D.VENDOR),
        (T.TRANSFER, NON, D.WAREHOUSE), (T.TRANSFER, NON, D.OFFICE),
        (T.SAMPLE, RET, D.CUSTOMER), (T.SAMPLE, NON, D.OFFICE), (T.SAMPLE, RET, D.TRANSPORTER),
    ]
    for combo in valid:
        assert mp.check_combination(*combo) == [], combo
    invalid = {
        (T.OUTWARD, NON, D.WAREHOUSE): {"destination_not_allowed"},
        (T.OUTWARD, RET, D.OFFICE): {"destination_not_allowed"},
        (T.INWARD, RET, D.VENDOR): {"return_type_not_allowed"},
        (T.INWARD, NON, D.WAREHOUSE): {"destination_not_allowed"},
        (T.RETURN, RET, D.WAREHOUSE): {"destination_not_allowed"},
        (T.JOB_WORK, NON, D.FABRICATOR): {"job_work_must_be_returnable"},
        (T.JOB_WORK, RET, D.CUSTOMER): {"destination_not_allowed"},
        (T.JOB_WORK, NON, D.CUSTOMER): {"job_work_must_be_returnable", "destination_not_allowed"},
        (T.TRANSFER, RET, D.WAREHOUSE): {"return_type_not_allowed"},
        (T.TRANSFER, NON, D.CUSTOMER): {"destination_not_allowed"},
        (T.SAMPLE, RET, D.WAREHOUSE): {"destination_not_allowed"},
    }
    for combo, codes in invalid.items():
        problems = mp.check_combination(*combo)
        assert {p.code for p in problems} == codes, combo
        assert all(p.field in ("return_type", "destination_type") for p in problems)
    # the whole matrix is consistent with the rule table: a problem exactly when the rule excludes the pair
    for t in T:
        rule = mp.POLICY[t]
        for r in R:
            for d in D:
                expected = (r not in rule.return_types) + (d not in rule.destinations)
                assert len(mp.check_combination(t, r, d)) == expected, (t, r, d)


def test_defaults_direction_and_party_roles() -> None:
    assert mp.default_return_type(T.JOB_WORK) is RET and mp.POLICY[T.JOB_WORK].forced_returnable
    assert mp.default_return_type(T.SAMPLE) is RET and mp.default_return_type(T.OUTWARD) is NON
    assert mp.direction(T.INWARD) == "inward" and mp.direction(T.RETURN) == "inward"
    assert all(mp.direction(t) == "outward" for t in (T.OUTWARD, T.JOB_WORK, T.TRANSFER, T.SAMPLE))
    assert mp.party_role_ok(D.CUSTOMER, ["customer"]) and not mp.party_role_ok(D.CUSTOMER, ["vendor"])
    assert mp.party_role_ok(D.FABRICATOR, ["job_worker"]) and mp.party_role_ok(D.FABRICATOR, ["fabricator", "vendor"])
    assert mp.party_role_ok(D.TRANSPORTER, []) and not mp.party_role_ok(D.VENDOR, ["customer"])
    assert mp.LOCATION_DESTINATIONS == {D.WAREHOUSE, D.OFFICE}


@pytest.mark.parametrize("challan_type", list(T))
def test_every_type_accepts_its_default_return_type(challan_type: T) -> None:
    rule = mp.POLICY[challan_type]
    assert rule.default_return in rule.return_types
    assert rule.destinations, challan_type
