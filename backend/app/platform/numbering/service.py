"""Document number allocation (called late in the business transaction).

A rollback consumes nothing; numbers are registered in ``issued_document_number`` and never reused.
Counters only increase. ``preview`` shows the next number without allocating it.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.errors import Conflict
from app.platform.numbering.models import DocumentSequence, IssuedDocumentNumber

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

_TOKEN = re.compile(r"\{([a-z_]+)(?::(0\d))?\}")


class SequenceCollision(Conflict):
    code = "sequence_collision"


def period_key(reset_policy: str, document_date: date, fy_start_month: int = 4) -> str:
    if reset_policy == "never":
        return "all"
    if reset_policy == "yearly":
        return str(document_date.year)
    start_year = document_date.year if document_date.month >= fy_start_month else document_date.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def render(template: str, *, seq: int, document_date: date, period: str, tokens: dict[str, str]) -> str:
    def sub(match: re.Match[str]) -> str:
        name, width = match.group(1), match.group(2)
        if name == "seq":
            return str(seq).zfill(int(width or "04"))
        if name == "yyyy":
            return f"{document_date.year:04d}"
        if name == "yy":
            return f"{document_date.year % 100:02d}"
        if name == "fy":
            return period
        if name in tokens:
            value = tokens[name]
            if not re.fullmatch(r"[A-Z0-9]{1,8}", value):
                raise ValueError(f"token {name} must be 1-8 uppercase letters/digits")
            return value
        raise ValueError(f"unknown numbering token {{{name}}}")

    return _TOKEN.sub(sub, template)


def _ensure_sequence(uow: UnitOfWork, key: str, branch_id: uuid.UUID | None) -> DocumentSequence:
    from app.registry import get_registry

    stmt = select(DocumentSequence).where(
        DocumentSequence.company_id == uow.actor.company_id,
        DocumentSequence.sequence_key == key,
        DocumentSequence.branch_id.is_(None) if branch_id is None else DocumentSequence.branch_id == branch_id,
        DocumentSequence.archived_at.is_(None),
    )
    seq = uow.session.scalars(stmt).first()
    if seq is not None:
        return seq
    definition = get_registry().sequences.get(key)
    if definition is None:
        raise KeyError(f"sequence {key!r} is not registered")
    now = uow.now()
    uow.session.execute(
        pg_insert(DocumentSequence)
        .values(
            id=uuid.uuid7(),
            company_id=uow.actor.company_id,
            branch_id=branch_id,
            sequence_key=key,
            name=definition.name,
            format_template=definition.format_template,
            reset_policy=definition.reset_policy,
            start_value=definition.start_value,
            created_at=now,
            updated_at=now,
            version=1,
        )
        .on_conflict_do_nothing()
    )
    return uow.session.scalars(stmt).one()


def allocate(
    uow: UnitOfWork,
    sequence_key: str,
    *,
    document_date: date,
    resource_type: str,
    resource_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
    tokens: dict[str, str],
) -> str:
    seq = _ensure_sequence(uow, sequence_key, branch_id)
    period = period_key(seq.reset_policy, document_date, seq.financial_year_start_month)
    for _attempt in range(3):
        value = uow.session.execute(
            text(
                """
                INSERT INTO document_sequence_counter (sequence_id, company_id, period_key, next_value)
                VALUES (:s, :c, :p, :start + 1)
                ON CONFLICT (sequence_id, period_key)
                DO UPDATE SET next_value = document_sequence_counter.next_value + 1
                RETURNING next_value - 1
                """
            ),
            {"s": seq.id, "c": uow.actor.company_id, "p": period, "start": seq.start_value},
        ).scalar_one()
        number = render(seq.format_template, seq=int(value), document_date=document_date, period=period, tokens=tokens)
        inserted = uow.session.execute(
            pg_insert(IssuedDocumentNumber)
            .values(
                id=uuid.uuid7(),
                company_id=uow.actor.company_id,
                sequence_key=sequence_key,
                document_number=number,
                sequence_id=seq.id,
                period_key=period,
                seq_value=int(value),
                resource_type=resource_type,
                resource_id=resource_id,
                issued_at=uow.now(),
                issued_by=uow.actor.user_id,
            )
            .on_conflict_do_nothing()
            .returning(IssuedDocumentNumber.id)
        ).first()
        if inserted is not None:
            return number
    raise SequenceCollision(f"could not allocate a unique number for {sequence_key}")


def preview(uow: UnitOfWork, sequence_key: str, *, document_date: date, tokens: dict[str, str]) -> str:
    seq = _ensure_sequence(uow, sequence_key, None)
    period = period_key(seq.reset_policy, document_date, seq.financial_year_start_month)
    current = uow.session.execute(
        text("SELECT next_value FROM document_sequence_counter WHERE sequence_id = :s AND period_key = :p"),
        {"s": seq.id, "p": period},
    ).scalar()
    value = int(current) if current is not None else seq.start_value
    return render(seq.format_template, seq=value, document_date=document_date, period=period, tokens=tokens)


def register_existing(
    uow: UnitOfWork, sequence_key: str, *, document_number: str, seq_value: int, period: str,
    resource_type: str, resource_id: uuid.UUID,
) -> None:
    """Migration helper: register a legacy number and move the counter past it (never backwards)."""
    seq = _ensure_sequence(uow, sequence_key, None)
    uow.session.execute(
        pg_insert(IssuedDocumentNumber)
        .values(
            id=uuid.uuid7(), company_id=uow.actor.company_id, sequence_key=sequence_key,
            document_number=document_number, sequence_id=seq.id, period_key=period, seq_value=seq_value,
            resource_type=resource_type, resource_id=resource_id, issued_at=uow.now(), issued_by=None,
        )
        .on_conflict_do_nothing()
    )
    uow.session.execute(
        text(
            """
            INSERT INTO document_sequence_counter (sequence_id, company_id, period_key, next_value)
            VALUES (:s, :c, :p, :v + 1)
            ON CONFLICT (sequence_id, period_key)
            DO UPDATE SET next_value = GREATEST(document_sequence_counter.next_value, EXCLUDED.next_value)
            """
        ),
        {"s": seq.id, "c": uow.actor.company_id, "p": period, "v": seq_value},
    )
