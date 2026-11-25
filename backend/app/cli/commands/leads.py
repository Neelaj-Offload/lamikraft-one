"""``lk import leads``: load the leads spreadsheet into the lead pipeline (re-runnable; dry run by default).

    lk import leads FILE.xlsx --as EMAIL [--company KEY] [--apply]
        [--owner "Priyanka Khanna=priyanka@example.com" ...] [--default-owner EMAIL]

Without ``--apply`` the import runs inside a transaction that is rolled back, so the report shows exactly what an
apply would do. Every "Asign To" name in the sheet must map to a member (``--owner``), or ``--default-owner`` takes
the unmapped rows; otherwise those rows are rejected. See ``app/modules/parties/lead_import.py``.
"""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path
from typing import Any

from app.cli import CliError, arg, command, group, out
from app.cli.commands.migration import cli_actor, company_id_for

group("import", "Load spreadsheets (leads) into Lamikraft One")


class _Rollback(Exception):
    def __init__(self, report: Any) -> None:
        self.report = report


def _member_id(company_id: uuid.UUID, email: str) -> uuid.UUID:
    from sqlalchemy import select

    from app.platform.authz.context import ActorContext
    from app.platform.identity.models import AppUser, Membership
    from app.platform.uow import UnitOfWork

    with UnitOfWork(ActorContext.system(company_id, reason="cli")) as uow:
        user_id = uow.session.scalar(
            select(AppUser.id)
            .join(Membership, Membership.user_id == AppUser.id)
            .where(AppUser.email_normalized == email.strip().lower(), Membership.company_id == company_id)
        )
    if user_id is None:
        raise CliError(f"no member with email {email}", hint="invite the person first (Settings → People)")
    return user_id


@command(
    "import",
    "leads",
    help="Import the leads spreadsheet (dry run unless --apply)",
    arguments=[
        arg("file", type=Path, help="the .xlsx file"),
        arg("--as", dest="as_email", required=True, help="the operator (needs parties.party.create and assign)"),
        arg("--company", default=None, help="company key (default: the only company)"),
        arg("--apply", action="store_true", help="write the leads (default: dry run, nothing is saved)"),
        arg("--owner", action="append", default=[], metavar="NAME=EMAIL", help="map an 'Asign To' name to a member"),
        arg("--default-owner", default=None, metavar="EMAIL", help="owner for rows whose name is not mapped"),
        arg("--show", type=int, default=20, help="how many issue lines to print (default 20)"),
    ],
)
def import_leads(args: argparse.Namespace) -> int | None:
    from app.modules.parties import lead_import
    from app.platform.uow import UnitOfWork
    from app.registry import get_registry

    get_registry()  # module hooks: member actors, source readers
    if not args.file.is_file():
        raise CliError(f"no file {args.file}")
    company_id, key = company_id_for(args.company)
    actor = cli_actor(company_id, args.as_email, "parties.party.create")
    owners: dict[str, uuid.UUID] = {}
    for pair in args.owner:
        name, sep, email = pair.partition("=")
        if not sep or not name.strip() or not email.strip():
            raise CliError(f"--owner needs NAME=EMAIL, got {pair!r}")
        owners[lead_import.owner_key(name)] = _member_id(company_id, email)
    default_owner = _member_id(company_id, args.default_owner) if args.default_owner else None

    sheet = lead_import.parse_sheet(args.file)
    try:
        with UnitOfWork(actor) as uow:
            report = lead_import.apply_rows(uow, sheet, owners, default_owner=default_owner)
            if not args.apply:
                raise _Rollback(report)
    except _Rollback as rb:
        report = rb.report

    mode = "applied" if args.apply else "dry run (nothing saved; add --apply)"
    out(f"company {key}: {mode}")
    out(f"rows read: {len(sheet.rows) + len([i for i in sheet.issues if i.severity == 'rejected'])}")
    out(f"created: {len(report.created)}  updated: {len(report.updated)}  unchanged: {len(report.unchanged)}  "
        f"rejected: {len(report.rejected)}")
    if report.sources_created:
        out(f"new lead sources: {', '.join(report.sources_created)}")
    unmapped = sorted({i.message for i in report.rejected if i.message.startswith("Owner not mapped")})
    for line in unmapped:
        out(f"  {line}")
    for issue in report.issues[: args.show]:
        out(f"  row {issue.row_no} [{issue.severity}] {issue.company or ''}: {issue.message}")
    if len(report.issues) > args.show:
        out(f"  … {len(report.issues) - args.show} more (use --show)")
    return None
