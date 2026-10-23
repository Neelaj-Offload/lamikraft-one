"""UI state sections that modules contribute to the session bootstrap and the UI poll.

``GET /api/v1/session/bootstrap`` (module ``ui``) returns every registered section; ``GET /api/v1/ui/poll``
returns the sections with ``in_poll=True`` (Inbox counts, current briefing version, ...). Modules register
in their manifest ``on_load`` so ``ui`` never imports them. A failing section is reported as unavailable and
never breaks the bootstrap (an AI or briefing outage must not stop sign-in).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.platform.uow import UnitOfWork

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UiSection:
    key: str  # snake_case, e.g. "inbox_counts", "briefing", "integrations"
    build: Callable[[UnitOfWork], dict[str, Any]]  # runs in the caller's (authenticated) unit of work
    in_poll: bool = True


_SECTIONS: dict[str, UiSection] = {}


def register_ui_section(section: UiSection) -> None:
    _SECTIONS[section.key] = section


def registered_sections() -> tuple[UiSection, ...]:
    return tuple(_SECTIONS[k] for k in sorted(_SECTIONS))


def build_sections(uow: UnitOfWork, *, poll_only: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for section in registered_sections():
        if poll_only and not section.in_poll:
            continue
        try:
            out[section.key] = section.build(uow)
        except Exception as exc:  # isolate contributors; the session must still bootstrap
            log.warning("ui.section_failed", section=section.key, error=type(exc).__name__)
            out[section.key] = {"status": "unavailable"}
    return out
