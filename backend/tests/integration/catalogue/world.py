"""The canonical fixture world for the catalogue lane's tests (docs/architecture/fixtures.md).

A test company with the Slice-1 personas (fixture keys from ``app.seed.world.keys``), each acting through the role
template named in the fixtures, then the lane's own seeds run exactly as ``lk seed demo`` runs them: parties (20),
catalogue (30), pricing and commercial (40), dated party changes (55). The identity lane owns the real member-actor builder; until it is
merged, tests register a builder that resolves a persona's template grants from the frozen permission catalogue.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from types import MappingProxyType

import pytest

from app.core.clock import FrozenClock
from app.platform.authz import actors as actor_registry
from app.platform.authz.catalogue import template_grants
from app.platform.authz.context import ActorContext, Channel
from app.seed.context import D0, SeedContext
from app.seed.world import keys
from tests.support import create_company, create_user

_PERSONAS: dict[tuple[uuid.UUID, uuid.UUID], ActorContext] = {}


def _builder(company_id: uuid.UUID, user_id: uuid.UUID, channel: Channel) -> ActorContext | None:
    actor = _PERSONAS.get((company_id, user_id))
    return actor.with_(channel=channel) if actor is not None else None


@dataclass
class World:
    company_id: uuid.UUID
    branch_id: uuid.UUID
    ctx: SeedContext
    actors: dict[str, ActorContext] = field(default_factory=dict)

    def ref(self, key: str) -> uuid.UUID:
        return self.ctx.ref(key)

    def actor(self, user_key: str) -> ActorContext:
        return self.actors[user_key]

    def user_id(self, user_key: str) -> uuid.UUID:
        return self.ctx.ref(user_key)


def build_personas(company_key: str | None = None) -> World:
    """A company with the Slice-1 personas (no business data yet)."""
    company_id, branch_id = create_company(company_key)
    grants = template_grants()
    people = {k: p for k, p in keys.PEOPLE.items() if p.slice_no == 1}
    ids = {k: create_user(company_id, p.name) for k, p in people.items()}
    teams: dict[str, set[uuid.UUID]] = {}
    for k, p in people.items():
        if p.team:
            teams.setdefault(p.team, set()).add(ids[k])
    world = World(company_id, branch_id, SeedContext(company_id=company_id, clock=FrozenClock(D0), refs=dict(ids)))
    for k, p in people.items():
        peers = frozenset(teams.get(p.team, set()) - {ids[k]}) if p.team else frozenset()
        actor = ActorContext(
            actor_type="user",
            company_id=company_id,
            user_id=ids[k],
            display_name=p.name,
            branch_ids=frozenset({branch_id}),
            team_peer_user_ids=peers,
            permissions=MappingProxyType(dict(grants[p.role_template])),
            channel="test",
        )
        world.actors[k] = actor
        _PERSONAS[(company_id, ids[k])] = actor
    return world


def seed_world(world: World) -> World:
    """Run the lane's seeds in manifest order (parties 20, catalogue 30, pricing and commercial 40, party changes 55)."""
    from app.seed.world.catalogue import seed_catalogue
    from app.seed.world.commercial import seed_commercial
    from app.seed.world.parties import seed_parties, seed_party_changes
    from app.seed.world.pricing import seed_pricing

    seed_parties(world.ctx)
    seed_catalogue(world.ctx)
    seed_pricing(world.ctx)
    seed_commercial(world.ctx)
    seed_party_changes(world.ctx)
    return world


def category_name(key: str) -> str:
    """Name of a seeded category by its refs key (``CAT_SERVEWARE``); keys.py has no taxonomy constants yet."""
    from app.seed.world.catalogue import CATEGORIES

    return CATEGORIES[key][0]


def subcategory_name(key: str) -> str:
    """Name of a seeded subcategory by its refs key (``SUB_TRAYS``)."""
    from app.seed.world.catalogue import CATEGORIES

    return next(name for _cat, _order, subs in CATEGORIES.values() for sub_key, name in subs if sub_key == key)


def product_name(key: str) -> str:
    """Name of a seeded product by its fixture key (``OAK_TRAY``)."""
    from app.seed.world.catalogue import SLICE1_PRODUCTS

    return next(p.name for p in SLICE1_PRODUCTS if p.key == key)


def next_party_number() -> str:
    """The number the real allocator gives the next party: one after the seeded customers (fixtures.md §1 rule 4)."""
    from app.modules.parties.events import PARTY_SEQUENCE
    from app.seed.world.parties import SLICE1_CUSTOMERS

    return PARTY_SEQUENCE.format_template.format(seq=PARTY_SEQUENCE.start_value + len(SLICE1_CUSTOMERS))


@pytest.fixture
def member_actors() -> Iterator[None]:
    previous = actor_registry._builder
    actor_registry.register_member_actor_builder(_builder)
    try:
        yield
    finally:
        actor_registry.register_member_actor_builder(previous)
        _PERSONAS.clear()


@pytest.fixture
def personas(db: None, member_actors: None) -> World:
    return build_personas()


@pytest.fixture
def world(personas: World) -> World:
    return seed_world(personas)
