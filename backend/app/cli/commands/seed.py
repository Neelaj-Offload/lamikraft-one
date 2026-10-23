"""``lk seed demo``: create or refresh the canonical demo world (docs/architecture/fixtures.md)."""

from __future__ import annotations

import argparse
from datetime import date

from app.cli import CliError, arg, command, group, out

group("seed", "Demo and fixture data")


def _anchor(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("use YYYY-MM-DD") from None


@command(
    "seed",
    "demo",
    help="Seed the demo company crown-demo through the module services (idempotent)",
    arguments=[
        arg("--anchor-date", type=_anchor, default=None, help="D0 work date, YYYY-MM-DD (default: today, Asia/Kolkata)"),
        arg("--slice", type=int, default=1, dest="slice_max", help="highest slice whose fixtures are created (default 1)"),
    ],
)
def seed_demo(args: argparse.Namespace) -> int | None:
    from app.core.config import get_settings
    from app.seed.runner import installed_seeds, run_demo_seed

    if args.slice_max < 1:
        raise CliError("--slice must be 1 or more")
    if get_settings().is_production:
        raise CliError("refusing to seed demo data while LK_ENV=production")
    seeds = installed_seeds(args.slice_max)
    out(f"seeding {len(seeds)} seed(s): " + ", ".join(f"{s.order}:{s.name}" for s in seeds))
    ctx = run_demo_seed(anchor=args.anchor_date, slice_max=args.slice_max)
    out(f"company {ctx.company_id} anchored at {ctx.facts.get('anchor_date')} (slice <= {ctx.slice_max})")
    out(f"references: {len(ctx.refs)} ({', '.join(sorted(ctx.refs))})")
    out("sign in as a demo user with: lk demo sign-in-link <USER_KEY>")
    return None
