"""Approvals: exact-content binding, separation of duties, staleness and expiry (scenario F foundations)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.errors import Conflict, Forbidden, NotFound
from app.modules.approvals import service as approvals
from app.modules.approvals.service import ApprovalHandler, TargetRef
from app.platform.authz.permissions import Scope
from app.platform.uow import UnitOfWork
from tests.support import actor, create_company, create_user

pytestmark = pytest.mark.db

_versions: dict[uuid.UUID, int] = {}
_applied: list[str] = []


def _handler() -> None:
    approvals.register_handler(
        ApprovalHandler(
            kind="test.thing.review",
            approve_permission="sales.quote.approve",
            current_version=lambda uow, t: _versions.get(t.target_id),
            on_approved=lambda uow, p: _applied.append(f"approved:{p.id}"),
            on_rejected=lambda uow, p: _applied.append(f"rejected:{p.id}"),
        )
    )


@pytest.fixture
def world(db: None):  # type: ignore[no-untyped-def]
    previous = approvals._HANDLERS.get("test.thing.review")
    _handler()
    company, _ = create_company()
    requester = create_user(company, "Meera")
    approver = create_user(company, "Sahil")
    target = uuid.uuid7()
    _versions[target] = 3
    req = actor(company, user_id=requester, permissions={"sales.quote.approve": Scope.COMPANY})
    app = actor(company, user_id=approver, permissions={"sales.quote.approve": Scope.COMPANY})
    try:
        yield company, req, app, target
    finally:  # fixture-scoped: the test handler never outlives this test
        if previous is None:
            approvals._HANDLERS.pop("test.thing.review", None)
        else:
            approvals._HANDLERS["test.thing.review"] = previous


def _submit(req, target, content=None):  # type: ignore[no-untyped-def]
    with UnitOfWork(req) as uow:
        p = approvals.submit(
            uow,
            kind="test.thing.review",
            targets=[TargetRef("test.thing", target, 3)],
            content=content or {"qty": "240", "unit_price": "24.0000"},
            title="Review Nordhaus quote",
        )
        return p.id, p.content_hash, p.version


def test_requester_cannot_approve_own_request(world) -> None:  # type: ignore[no-untyped-def]
    _company, req, _app, target = world
    pid, digest, version = _submit(req, target)
    with pytest.raises(Forbidden):
        with UnitOfWork(req) as uow:
            approvals.decide(uow, pid, decision="approve", content_hash_seen=digest, expected_version=version)


def test_approval_binds_to_exact_content(world) -> None:  # type: ignore[no-untyped-def]
    _company, req, app, target = world
    pid, digest, version = _submit(req, target)
    with pytest.raises(Conflict, match="content"):
        with UnitOfWork(app) as uow:
            approvals.decide(uow, pid, decision="approve", content_hash_seen="0" * 64, expected_version=version)
    with UnitOfWork(app) as uow:
        p = approvals.decide(uow, pid, decision="approve", content_hash_seen=digest, expected_version=version)
        assert p.status == "approved"
    assert f"approved:{pid}" in _applied


def test_changed_target_invalidates_and_needs_fresh_approval(world) -> None:  # type: ignore[no-untyped-def]
    _company, req, app, target = world
    pid, digest, version = _submit(req, target)
    _versions[target] = 4  # quantity changed after submission
    with UnitOfWork(app) as uow:
        outcome = approvals.decide(uow, pid, decision="approve", content_hash_seen=digest, expected_version=version)
    with pytest.raises(Conflict, match="fresh review"):
        approvals.raise_if_not_decided(outcome)
    with UnitOfWork(app) as uow:
        assert approvals.get(uow, pid).status == "invalidated"
    assert f"approved:{pid}" not in _applied


def test_new_request_supersedes_pending_one(world) -> None:  # type: ignore[no-untyped-def]
    _company, req, app, target = world
    first, _, _ = _submit(req, target)
    second, digest2, v2 = _submit(req, target, content={"qty": "250"})
    with UnitOfWork(app) as uow:
        assert approvals.get(uow, first).status == "superseded"
        assert approvals.decide(uow, second, decision="reject", content_hash_seen=digest2, expected_version=v2, reason="price too low").status == "rejected"


def test_expired_request_cannot_be_approved(world, frozen_clock) -> None:  # type: ignore[no-untyped-def]
    _company, req, app, target = world
    pid, digest, version = _submit(req, target)
    frozen_clock.advance(days=8)
    with UnitOfWork(app) as uow:
        outcome = approvals.decide(uow, pid, decision="approve", content_hash_seen=digest, expected_version=version)
    with pytest.raises(Conflict, match="expired"):
        approvals.raise_if_not_decided(outcome)


def test_person_without_approve_permission_is_not_eligible(world) -> None:  # type: ignore[no-untyped-def]
    company, req, _app, target = world
    outsider = actor(company, user_id=create_user(company, "Kabir"), permissions={})
    pid, digest, version = _submit(req, target)
    with pytest.raises(NotFound):  # not visible to a non-approver: 404, not 403
        with UnitOfWork(outsider) as uow:
            approvals.decide(uow, pid, decision="approve", content_hash_seen=digest, expected_version=version)


def test_decision_table_enforces_separation_of_duties_in_db(world) -> None:  # type: ignore[no-untyped-def]
    from app.modules.approvals.models import ProposalDecision

    company, req, _app, target = world
    pid, digest, version = _submit(req, target)
    with pytest.raises(Exception, match="separation_of_duties"):
        with UnitOfWork(req) as uow:
            uow.add(ProposalDecision(proposal_id=pid, proposal_version=version, decision="approve", content_hash=digest,
                                     requested_by=req.user_id, decided_by=req.user_id, decided_at=uow.now() - timedelta(0)))
