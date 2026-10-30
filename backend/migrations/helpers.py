"""Migration helpers for the parts autogenerate cannot see.

- ``enable_tenant_rls(table)``: ENABLE + FORCE row-level security with the fail-closed policy
  ``company_id = NULLIF(current_setting('app.company_id', true), '')::uuid``.
- ``append_only(table)``: trigger rejecting UPDATE/DELETE (audit log, ledgers, issued revisions).
- ``enum_check(table, column, values)``: CHECK constraint from a Python StrEnum / tuple.
- ``immutable_columns(table, columns)``: trigger rejecting an UPDATE that changes any named column (business keys,
  issued numbers); other columns stay updatable.
- ``install_platform_functions()``: shared trigger functions (idempotent).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from alembic import op

POLICY = "tenant_isolation"


def install_platform_functions() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION lk_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'table % is append-only (% blocked)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END $$;
        """
    )


def enable_tenant_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS {POLICY} ON "{table}"')
    op.execute(
        f"""
        CREATE POLICY {POLICY} ON "{table}"
            USING (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
            WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::uuid)
        """
    )


def append_only(table: str) -> None:
    op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_append_only ON "{table}"')
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON "{table}"
            FOR EACH ROW EXECUTE FUNCTION lk_reject_mutation()
        """
    )
    op.execute(f'REVOKE UPDATE, DELETE ON "{table}" FROM lk_app')


def enum_check(table: str, column: str, values: Iterable[str], name: str | None = None) -> None:
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    op.create_check_constraint(name or f"{column}_values", table, f"{column} IN ({quoted})")


def grant_app(table: str, privileges: str = "SELECT, INSERT, UPDATE, DELETE") -> None:
    op.execute(f'GRANT {privileges} ON "{table}" TO lk_app')


_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _identifier(name: str) -> str:
    if not _IDENTIFIER.match(name) or len(name) > 50:
        raise ValueError(f"not a plain lower-case SQL identifier: {name!r}")
    return name


def immutable_columns(table: str, columns: Sequence[str]) -> None:
    """Reject any UPDATE that changes one of ``columns`` of ``table`` (``integrity_constraint_violation``).

    Installs ``lk_<table>_immutable()`` and ``trg_<table>_immutable`` (``BEFORE UPDATE OF <columns>``); calling it
    again for the same table replaces both, so the column list can grow in a later migration. The service layer
    still refuses the change with a proper problem response; the trigger is the database's backstop.
    """
    table = _identifier(table)
    cols = [_identifier(c) for c in columns]
    if not cols:
        raise ValueError("immutable_columns needs at least one column")
    if len(set(cols)) != len(cols):
        raise ValueError(f"duplicate columns: {cols}")
    checks = "\n".join(
        f"""    IF NEW."{c}" IS DISTINCT FROM OLD."{c}" THEN
        RAISE EXCEPTION '{table}.{c} is immutable' USING ERRCODE = 'integrity_constraint_violation';
    END IF;"""
        for c in cols
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION lk_{table}_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
{checks}
            RETURN NEW;
        END $$;
        """
    )
    op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_immutable ON "{table}"')
    column_list = ", ".join(f'"{c}"' for c in cols)
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OF {column_list} ON "{table}"
            FOR EACH ROW EXECUTE FUNCTION lk_{table}_immutable()
        """
    )
