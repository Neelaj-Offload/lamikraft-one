"""``lk admin``: the one-time first administrator and access-catalogue maintenance.

``create-first`` refuses when any admin membership exists. The password is read from stdin
(``--password-stdin``) or prompted twice on a terminal; it is never taken from arguments or environment.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.cli import EXIT_FAILURE, CliError, arg, command, group, out

group("admin", "First administrator and access catalogue")

DEFAULT_COMPANY_KEY = "lamikraft"


def _read_password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        value = sys.stdin.readline().rstrip("\r\n")
        if not value:
            raise CliError("no password on stdin")
        return value
    if not sys.stdin.isatty():
        raise CliError("a password is required", hint="pipe it with --password-stdin or run in a terminal")
    first = getpass.getpass("Password (12-256 characters): ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise CliError("the passwords do not match")
    return first


@command(
    "admin",
    "create-first",
    help="Create the first administrator (refuses when any admin membership exists)",
    arguments=[
        arg("--email", required=True, help="the administrator's email (sign-in name)"),
        arg("--name", required=True, help="display name"),
        arg("--password-stdin", action="store_true", help="read the password from the first line of stdin"),
        arg("--company-key", default=DEFAULT_COMPANY_KEY, help=f"company key (default {DEFAULT_COMPANY_KEY})"),
        arg("--company-name", default=None, help="legal name when the company is created (default: the key)"),
        arg("--display-company-name", default=None, help="display name when the company is created"),
    ],
)
def create_first(args: argparse.Namespace) -> int | None:
    from app.core.errors import AppError
    from app.platform.identity import service
    from app.platform.identity.provisioning import CompanySpec

    password = _read_password(args)
    legal = args.company_name or args.company_key
    spec = CompanySpec(
        company_key=args.company_key,
        legal_name=legal,
        display_name=args.display_company_name or legal,
        is_demo=False,
    )
    try:
        result = service.create_first_admin(email=args.email, display_name=args.name, password=password, company=spec)
    except AppError as exc:
        if exc.code == "admin_exists":
            raise CliError(exc.detail, code=EXIT_FAILURE, hint="sign in as an existing administrator instead") from None
        raise CliError(f"{exc.code}: {exc.detail}") from None
    out(f"company {args.company_key}: {'created' if result.company_created else 'exists'} ({result.company_id})")
    out(f"administrator {args.email}: created (membership {result.membership_id})")
    return None


@command("admin", "sync-access", help="Sync the permission catalogue, legacy aliases and system roles of every company")
def sync_access(args: argparse.Namespace) -> int | None:
    """The same sync the API runs at startup (``app.platform.identity.startup``), on demand."""
    from app.platform.identity import roles

    result = roles.sync_access_all(origin="cli")
    out(f"permissions: {result['permissions']} synced")
    out(f"companies: {result['companies']} with system roles in sync")
    return None
