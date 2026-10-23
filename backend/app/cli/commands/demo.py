"""``lk demo sign-in-link``: a one-time, 15-minute sign-in link for a demo user (demo companies only).

The token travels in the ``#t=`` fragment so it never reaches a server log or a Referer header.
"""

from __future__ import annotations

import argparse

from app.cli import CliError, arg, command, group, out

group("demo", "Demo company helpers")


@command(
    "demo",
    "sign-in-link",
    help="Print a one-time sign-in link for a demo user (fixture key such as MEERA, or an email)",
    arguments=[
        arg("user_key", metavar="USER_KEY", help="fixture key (SAHIL, MEERA, ...) or the member's email"),
        arg("--company", default=None, help="demo company key (default crown-demo)"),
    ],
)
def sign_in_link(args: argparse.Namespace) -> int | None:
    from app.core.config import get_settings
    from app.core.errors import AppError
    from app.platform.identity import service
    from app.seed.world.keys import COMPANY_KEY, PEOPLE

    ref: str = args.user_key.strip()
    person = PEOPLE.get(ref.upper())
    if person is not None:
        email = person.email
    elif "@" in ref:
        email = ref
    else:
        known = ", ".join(sorted(PEOPLE))
        raise CliError(f"unknown user {ref!r}", hint=f"use a fixture key ({known}) or an email")
    try:
        link = service.issue_demo_link(company_key=args.company or COMPANY_KEY, email=email)
    except AppError as exc:
        raise CliError(f"{exc.code}: {exc.detail}", hint="seed the demo company first: lk seed demo") from None
    port = get_settings().web_port
    out(f"http://127.0.0.1:{port}/demo-sign-in#t={link.token}")
    out(f"# {link.display_name}; one use; expires {link.expires_at.isoformat()}")
    return None
