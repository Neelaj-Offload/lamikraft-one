"""A test-only parent resource for notes: a temporary table with a real ResourcePolicy.

Notes are polymorphic children; they are authorised only through the parent's ResourcePolicy. The parent
here uses the frozen ``sales.quote.*`` keys (all four scopes) so own/company scope, read-only and
not-visible cases are exercised exactly as a domain module's records would be.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy import DateTime, Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.platform.authz import policy as policy_module
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import ResourcePolicy, register_policy
from app.platform.uow import UnitOfWork
from tests.integration.org.platform_lane import ApiClient, api_client
from tests.support import create_company

PARENT_TYPE = "test.note_parent"


class _TestBase(DeclarativeBase):
    """Separate metadata: never part of the application schema or its RLS contract."""


class NoteParent(_TestBase):
    __tablename__ = "lk_test_note_parent"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid7)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


POLICY = ResourcePolicy(
    resource_type=PARENT_TYPE,
    model=NoteParent,
    permission_prefix="sales.quote",
    owner_columns=("owner_user_id",),
)


@pytest.fixture
def company(db: None) -> tuple[uuid.UUID, uuid.UUID]:
    return create_company()


@pytest.fixture
def api(db: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiClient]:
    with api_client(monkeypatch) as client:
        yield client


@pytest.fixture
def parent_table(db: None) -> Iterator[type[NoteParent]]:
    with UnitOfWork(ActorContext.system(None, reason="test-setup")) as uow:
        uow.session.execute(
            text(
                "CREATE TEMP TABLE lk_test_note_parent (id uuid PRIMARY KEY, company_id uuid NOT NULL, "
                "owner_user_id uuid NULL, archived_at timestamptz NULL)"
            )
        )
    register_policy(POLICY)
    try:
        yield NoteParent
    finally:
        policy_module._POLICIES.pop(PARENT_TYPE, None)
        policy_module._BY_MODEL.pop(NoteParent, None)


def make_parent(company_id: uuid.UUID, owner_user_id: uuid.UUID | None) -> uuid.UUID:
    parent_id = uuid.uuid7()
    with UnitOfWork(ActorContext.system(company_id, reason="test-setup")) as uow:
        uow.add(NoteParent(id=parent_id, company_id=company_id, owner_user_id=owner_user_id))
    return parent_id
