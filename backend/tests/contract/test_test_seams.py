"""The tasks/briefings test world fakes only what is not merged yet, and only while a fixture holds it.

The real modules register their seams in ``on_load`` (identity: the member-actor builder; parties and catalogue:
their SourceReaders). The world's fakes (sales readers, the ``sales.quote.review`` handler and the identity readers
that do not exist yet) must be registered by ``install`` and restored exactly by ``uninstall``, never at import,
so no lane's fake leaks into another lane's tests whatever the order (``tests/conftest.py::_seams_restored``
checks every test the same way).
"""

from __future__ import annotations

from app.core.clock import FrozenClock
from app.modules.approvals import service as approvals
from app.platform import sources
from app.platform.authz import actors
from app.registry import get_registry
from tests.conftest import D0, seam_registrations


def _module(obj: object) -> str:
    return getattr(obj, "__module__", "") or ""


def test_real_modules_own_the_seams_outside_fixtures() -> None:
    """Runs after every test module was imported (collection): a fake registered at import shows up here."""
    get_registry()
    assert _module(actors._builder) == "app.platform.identity.actors"
    assert _module(sources._READERS.get("parties.party")) == "app.modules.parties.service"
    for source_type, reader in sources._READERS.items():
        assert _module(reader).startswith("app."), f"{source_type} reader comes from {_module(reader)}"
    for kind, handler in approvals._HANDLERS.items():
        assert _module(handler.current_version).startswith("app."), f"approval handler {kind} is a test fake"


def test_world_install_is_restored_exactly() -> None:
    from tests.integration.briefings.world import FAKE_HANDLERS, FAKE_READERS, FakeWorld

    before = seam_registrations()
    w = FakeWorld(FrozenClock(D0))
    with w.installed():
        for source_type in FAKE_READERS:
            assert _module(sources._READERS[source_type]) == "tests.integration.briefings.world"
        for kind in FAKE_HANDLERS:
            assert _module(approvals._HANDLERS[kind].current_version) == "tests.integration.briefings.world"
        assert actors._builder is before["member_actor_builder"]  # the real builder stays in place
        assert sources._READERS["parties.party"] is before["readers"]["parties.party"]  # type: ignore[index]
    assert seam_registrations() == before
    w.uninstall()  # a second uninstall is a no-op
    assert seam_registrations() == before
