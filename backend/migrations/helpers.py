"""Migration helpers for the parts autogenerate cannot see.

- ``enable_tenant_rls(table)``: ENABLE + FORCE row-level security with the fail-closed policy
  ``company_id = NULLIF(current_setting('app.company_id', true), '')::uuid``.
- ``append_only(table)``: trigger rejecting UPDATE/DELETE (audit log, ledgers, issued revisions).
- ``enum_check(table, column, values)``: CHECK constraint from a Python StrEnum / tuple.
- ``install_platform_functions()``: shared trigger functions (idempotent).
"""

from __future__ import annotations

from collections.abc import Iterable

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
