"""Seed orchestrator for the canonical fixture world (``lk seed demo``; docs/architecture/fixtures.md).

1. Freeze a clock (``FrozenClock``) and make it the global business clock for the run.
2. Create the demo company ``crown-demo`` only when it is absent (identity provisioning).
3. Run every installed manifest's ``SeedDef`` with ``slice_no <= slice_max`` in ``(order, name)`` order. Each
   seed moves the clock to each fact's timestamp (``SeedContext.at``) and creates rows only through services.
4. After each seed, drain the outbox and runnable jobs inline so subscribers see events in creation order.
5. Remember the seeded references (``last_world()``; also written to ``backend/var/seed/<db>.json`` so another
   process — the test-support router behind an e2e server — can return them).
Re-running is idempotent: every seed keys its rows by business keys.
"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.core.clock import FrozenClock, SystemClock, get_clock, set_global_clock
from app.core.config import BACKEND_DIR, get_settings
from app.core.logging import get_logger
from app.seed.context import SeedContext, SeedDef
from app.seed.world import keys

log = get_logger("lk.seed")

_lock = threading.Lock()
_last_world: dict[str, Any] | None = None


def installed_seeds(slice_max: int) -> list[SeedDef]:
    from app.registry import get_registry

    seeds = [s for s in get_registry().seeds if isinstance(s, SeedDef) and s.slice_no <= slice_max]
    return sorted(seeds, key=lambda s: (s.order, s.name))


def _drain() -> int:
    from app.platform.jobs.worker import drain

    return drain()


def run_demo_seed(*, anchor: date | None = None, slice_max: int = 1, drain_events: bool = True) -> SeedContext:
    """Seed (or re-seed) the demo world anchored on ``anchor`` (default: today in the company zone)."""
    from app.seed.world.identity import d0_for, ensure_demo_company

    if slice_max < 1:
        raise ValueError("slice_max must be at least 1")
    previous = get_clock()
    if anchor is None:
        anchor = previous.now().astimezone(ZoneInfo(keys.ZONE)).date()
    d0 = d0_for(anchor)
    clock = FrozenClock(d0)
    set_global_clock(clock)
    try:
        company_id = ensure_demo_company(clock, d0)
        ctx = SeedContext(company_id=company_id, clock=clock, slice_max=slice_max)
        ctx.facts["d0"] = d0
        ctx.facts["anchor_date"] = anchor.isoformat()
        for seed in installed_seeds(slice_max):
            log.info("seed.run", seed=seed.name, order=seed.order)
            seed.run(ctx)
            if drain_events:
                _drain()
        ctx.at(d0)
        if drain_events:
            _drain()
    finally:
        set_global_clock(None if isinstance(previous, SystemClock) else previous)
    _remember(ctx)
    return ctx


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v)))


def world_summary(ctx: SeedContext) -> dict[str, Any]:
    return {
        "company_id": str(ctx.company_id),
        "company_key": keys.COMPANY_KEY,
        "slice_max": ctx.slice_max,
        "refs": {k: str(v) for k, v in sorted(ctx.refs.items())},
        "facts": _json_safe(ctx.facts),
    }


def _world_file() -> Path:
    return BACKEND_DIR / "var" / "seed" / f"{get_settings().db_name}.json"


def _remember(ctx: SeedContext) -> None:
    global _last_world
    summary = world_summary(ctx)
    with _lock:
        _last_world = summary
    try:
        path = _world_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:  # the in-process copy still serves the test-support router
        log.warning("seed.world_file_unwritable", error=type(exc).__name__)


def last_world() -> dict[str, Any] | None:
    """The references of the most recent seed in this process, else the one recorded for this database."""
    with _lock:
        if _last_world is not None:
            return dict(_last_world)
    path = _world_file()
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return None


def forget_world() -> None:
    global _last_world
    with _lock:
        _last_world = None
