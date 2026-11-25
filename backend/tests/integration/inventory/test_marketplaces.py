"""Marketplace stock sync (module 5): orders take stock out once, problems are held, free stock is pushed.

Spec: docs/superpowers/specs/2026-11-25-marketplace-sync-design.md
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.core.errors import Conflict, Forbidden, ValidationFailed
from app.modules.marketplaces import adapters
from app.modules.marketplaces import service as mk
from app.modules.marketplaces.models import MarketplaceChannel
from app.platform.uow import UnitOfWork
from app.seed.world import keys
from tests.integration.inventory.world import InvWorld

pytestmark = pytest.mark.db
SAHIL, RAVI, MEERA = keys.USERS.SAHIL, keys.USERS.RAVI, keys.USERS.MEERA


def _amazon(w: InvWorld) -> mk.ChannelRead:
    with UnitOfWork(w.actor(SAHIL)) as uow:
        return next(c for c in mk.list_channels(uow) if c.code == "amazon_in")


def _map(w: InvWorld, channel_id: object, sku: str, product: str = "OAK_TRAY", **extra: object) -> None:
    with UnitOfWork(w.actor(SAHIL)) as uow:
        mk.create_listing(uow, channel_id, mk.ListingCreate.model_validate({"product_id": str(w.ref(product)), "channel_sku": sku, **extra}))  # type: ignore[arg-type]


def _simulate(w: InvWorld, channel_id: object, sku: str, qty: int) -> mk.OrderRead:
    with UnitOfWork(w.actor(RAVI)) as uow:
        return mk._order_read(mk.simulate_order(uow, channel_id, mk.SimulatedOrder(channel_sku=sku, quantity=qty)))  # type: ignore[arg-type]


def test_default_channels_in_demo(inv_world: InvWorld) -> None:
    with UnitOfWork(inv_world.actor(MEERA)) as uow:
        channels = mk.list_channels(uow)
    assert [c.code for c in channels] == ["amazon_in", "flipkart", "pepperfry", "website"]
    assert all(c.mode == "demo" for c in channels) and channels[0].warehouse_id == inv_world.warehouse_id
    assert channels[0].capabilities["manage"].allowed is False  # sales reads only


def test_order_takes_stock_out_once_and_problems_are_held(inv_world: InvWorld) -> None:
    w = inv_world
    ch = _amazon(w)
    _map(w, ch.id, "LK-OAK-450")
    before = w.summary("OAK_TRAY")[0]
    posted = _simulate(w, ch.id, "LK-OAK-450", 3)
    assert posted.status == "posted" and posted.posting_id is not None and posted.is_demo
    assert w.summary("OAK_TRAY")[0] == before - 3
    unmapped = _simulate(w, ch.id, "NOT-MAPPED", 1)
    assert unmapped.status == "needs_attention" and "not mapped" in (unmapped.attention_reason or "")
    short = _simulate(w, ch.id, "LK-OAK-450", 999)
    assert short.status == "needs_attention" and "free stock" in (short.attention_reason or "")
    assert w.summary("OAK_TRAY")[0] == before - 3
    with UnitOfWork(w.actor(SAHIL)) as uow:  # importing the same external order again posts nothing
        channel = uow.session.get(MarketplaceChannel, ch.id)
        again = mk.import_order(uow, channel, adapters.ExternalOrder(posted.external_order_id, posted.ordered_at, "open",  # type: ignore[arg-type]
                                                                    (adapters.ExternalLine("LK-OAK-450", Decimal(3)),)))
    assert again is None and w.summary("OAK_TRAY")[0] == before - 3
    detail = mk.get_channel(w.actor(SAHIL), ch.id)
    assert detail.attention_count == 2 and len(detail.orders) == 3


def test_sync_pushes_free_stock_and_permissions(inv_world: InvWorld) -> None:
    w = inv_world
    ch = _amazon(w)
    _map(w, ch.id, "LK-MT-300", product="MAPLE_TRIVET")
    with UnitOfWork(w.actor(RAVI)) as uow:
        summary = mk.sync_channel(uow, ch.id)
    assert summary.error is None and summary.listings_pushed == 1
    listing = mk.get_channel(w.actor(SAHIL), ch.id).listings[0]
    assert Decimal(listing.last_pushed_qty or "0") == w.summary("MAPLE_TRIVET")[0]
    with pytest.raises(Forbidden), UnitOfWork(w.actor(MEERA)) as uow:
        mk.sync_channel(uow, ch.id)
    current = mk.get_channel(w.actor(SAHIL), ch.id).version
    with pytest.raises(ValidationFailed), UnitOfWork(w.actor(SAHIL)) as uow:  # no credentials -> no live mode
        mk.update_channel(uow, ch.id, mk.ChannelUpdate(expected_version=current, mode="live"))


# ---- Amazon Selling Partner API against a mocked transport ---------------------------------------------------------
@pytest.fixture
def amazon_env(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    fake = SimpleNamespace(
        amazon_lwa_client_id="client", amazon_lwa_client_secret=SecretStr("secret"), amazon_refresh_token=SecretStr("refresh"),
        amazon_seller_id="SELLER1", amazon_endpoint="https://sp.example.test", amazon_marketplace_id="A21TJRUUN4KGV",
    )
    monkeypatch.setattr(adapters, "get_settings", lambda: fake)
    return []


def _transport(calls: list[httpx.Request]) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        url = str(request.url)
        if url.startswith(adapters.LWA_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "tok"})
        if "/orderItems" in url:
            return httpx.Response(200, json={"payload": {"OrderItems": [{"SellerSKU": "LK-OAK-450", "QuantityOrdered": 2, "Title": "Oak tray"}]}})
        if "/orders/v0/orders" in url:
            return httpx.Response(200, json={"payload": {"Orders": [
                {"AmazonOrderId": "403-1111111-1111111", "PurchaseDate": "2026-10-12T03:00:00Z", "OrderStatus": "Unshipped"},
                {"AmazonOrderId": "403-2222222-2222222", "PurchaseDate": "2026-10-12T03:05:00Z", "OrderStatus": "Pending"},
            ]}})
        if "/listings/2021-08-01/items/" in url:
            return httpx.Response(200, json={"status": "ACCEPTED"})
        return httpx.Response(404, json={"errors": [{"message": "unexpected"}]})

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_amazon_live_sync_posts_orders_and_patches_quantity(inv_world: InvWorld, amazon_env: list[httpx.Request]) -> None:
    w = inv_world
    ch = _amazon(w)
    _map(w, ch.id, "LK-OAK-450", product_type="SERVING_TRAY")
    with UnitOfWork(w.actor(SAHIL)) as uow:
        mk.update_channel(uow, ch.id, mk.ChannelUpdate(expected_version=ch.version, mode="live"))
    before = w.summary("OAK_TRAY")[0]
    with UnitOfWork(w.actor(SAHIL)) as uow:
        summary = mk.sync_channel(uow, ch.id, client=_transport(amazon_env))
    assert summary.error is None and summary.orders_fetched == 1 and summary.orders_posted == 1  # Pending waits
    assert w.summary("OAK_TRAY")[0] == before - 2
    patch = next(r for r in amazon_env if r.method == "PATCH")
    assert patch.headers["x-amz-access-token"] == "tok" and "/items/SELLER1/LK-OAK-450" in str(patch.url)
    body = json.loads(patch.content)
    assert body["productType"] == "SERVING_TRAY"
    assert body["patches"][0]["value"][0]["quantity"] == int(before - 2)
    with pytest.raises(Conflict), UnitOfWork(w.actor(RAVI)) as uow:  # no simulated orders on a live channel
        mk.simulate_order(uow, ch.id, mk.SimulatedOrder(channel_sku="LK-OAK-450", quantity=1))
    with w.system() as uow:
        status = uow.session.execute(text("SELECT status FROM marketplaces_order WHERE external_order_id = '403-1111111-1111111'")).scalar()
    assert status == "posted"
