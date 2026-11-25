"""Marketplaces API (``/api/v1/marketplaces``): channels, listings, simulated orders (Demo) and the sync."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.http.authz_decl import requires
from app.core.http.deps import Actor
from app.modules.marketplaces import service as svc
from app.platform.uow import UnitOfWork

router = APIRouter(prefix="/marketplaces", tags=["marketplaces"])


@router.get("/channels", openapi_extra=requires(svc.READ))
def list_channels(actor: Actor) -> list[svc.ChannelRead]:
    """Amazon, Flipkart, Pepperfry and the website, each in Demo or Live mode."""
    with UnitOfWork(actor) as uow:
        return svc.list_channels(uow)


@router.get("/channels/{channel_id}", openapi_extra=requires(svc.READ))
def get_channel(actor: Actor, channel_id: uuid.UUID) -> svc.ChannelDetail:
    return svc.get_channel(actor, channel_id)


@router.patch("/channels/{channel_id}", openapi_extra=requires(svc.MANAGE))
def update_channel(actor: Actor, channel_id: uuid.UUID, body: svc.ChannelUpdate) -> svc.ChannelDetail:
    with UnitOfWork(actor) as uow:
        svc.update_channel(uow, channel_id, body)
    return svc.get_channel(actor, channel_id)


@router.post("/channels/{channel_id}/listings", status_code=201, openapi_extra=requires(svc.MANAGE))
def create_listing(actor: Actor, channel_id: uuid.UUID, body: svc.ListingCreate) -> svc.ChannelDetail:
    """Map a channel SKU (and ASIN or listing id) to a catalogue product."""
    with UnitOfWork(actor) as uow:
        svc.create_listing(uow, channel_id, body)
    return svc.get_channel(actor, channel_id)


@router.patch("/listings/{listing_id}", openapi_extra=requires(svc.MANAGE))
def update_listing(actor: Actor, listing_id: uuid.UUID, body: svc.ListingUpdate) -> svc.ChannelDetail:
    with UnitOfWork(actor) as uow:
        ln = svc.update_listing(uow, listing_id, body)
        channel_id = ln.channel_id
    return svc.get_channel(actor, channel_id)


@router.post("/channels/{channel_id}/simulate-order", status_code=201, openapi_extra=requires(svc.RUN))
def simulate_order(actor: Actor, channel_id: uuid.UUID, body: svc.SimulatedOrder) -> svc.OrderRead:
    """Demo: an order arrives for one listing and takes its stock out."""
    with UnitOfWork(actor) as uow:
        return svc._order_read(svc.simulate_order(uow, channel_id, body))


@router.post("/channels/{channel_id}/sync", openapi_extra=requires(svc.RUN))
def sync_channel(actor: Actor, channel_id: uuid.UUID) -> svc.SyncSummary:
    """Fetch new orders (Live), post their stock out, then push the free quantity of every push-enabled listing."""
    with UnitOfWork(actor) as uow:
        return svc.sync_channel(uow, channel_id)
