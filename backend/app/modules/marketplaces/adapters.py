"""Marketplace adapters (module 5): what a channel can fetch (orders) and push (free quantity).

``DemoAdapter`` keeps everything inside Lamikraft One (orders arrive through "Simulate an order"; pushes are
recorded). ``AmazonAdapter`` talks to the Selling Partner API with credentials from the environment only:
Login with Amazon token → Orders v0 (``getOrders``, ``getOrderItems``) → Listings Items 2021-08-01
(``patchListingsItem`` on ``fulfillment_availability``). The HTTP client is injectable so tests run against a mocked
transport; nothing here is called in Demo mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from app.core.config import get_settings

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"  # noqa: S105 -- the public Login with Amazon endpoint, not a secret


@dataclass(frozen=True)
class ExternalLine:
    sku: str
    quantity: Decimal
    title: str | None = None


@dataclass(frozen=True)
class ExternalOrder:
    external_order_id: str
    ordered_at: datetime
    status: str  # "open" or "cancelled" (the platform's own state, normalised)
    lines: tuple[ExternalLine, ...] = field(default_factory=tuple)


class AdapterError(Exception):
    """A platform call failed; the message is safe to show (no secrets)."""


class Adapter(Protocol):
    def fetch_orders(self, since: datetime | None) -> list[ExternalOrder]: ...

    def push_quantity(self, sku: str, quantity: int, *, product_type: str | None) -> None: ...


class DemoAdapter:
    """Demo: no platform is called. Orders come from "Simulate an order"; pushes are only recorded."""

    def fetch_orders(self, since: datetime | None) -> list[ExternalOrder]:
        return []

    def push_quantity(self, sku: str, quantity: int, *, product_type: str | None) -> None:
        return None


def amazon_configured() -> bool:
    s = get_settings()
    return bool(s.amazon_lwa_client_id and s.amazon_lwa_client_secret.get_secret_value()
                and s.amazon_refresh_token.get_secret_value() and s.amazon_seller_id)


class AmazonAdapter:
    """Selling Partner API (India: EU endpoint, marketplace A21TJRUUN4KGV)."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        if not amazon_configured():
            raise AdapterError("Amazon credentials are not configured (LK_AMAZON_* environment variables)")
        s = get_settings()
        self._client = client or httpx.Client(timeout=30)
        self._endpoint = s.amazon_endpoint.rstrip("/")
        self._marketplace = s.amazon_marketplace_id
        self._seller = s.amazon_seller_id
        self._token: str | None = None

    # ---- auth ---------------------------------------------------------------------------------------------------
    def _access_token(self) -> str:
        if self._token is None:
            s = get_settings()
            response = self._client.post(LWA_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": s.amazon_refresh_token.get_secret_value(),
                "client_id": s.amazon_lwa_client_id,
                "client_secret": s.amazon_lwa_client_secret.get_secret_value(),
            })
            if response.status_code != 200:
                raise AdapterError(f"Amazon sign-in failed ({response.status_code})")
            self._token = str(response.json()["access_token"])
        return self._token

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"x-amz-access-token": self._access_token(), "content-type": "application/json"}
        response = self._client.request(method, f"{self._endpoint}{path}", headers=headers, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("errors", [{}])[0].get("message", "")
            except ValueError:
                detail = ""
            raise AdapterError(f"Amazon {method} {path.split('?')[0]} failed ({response.status_code}) {detail}".strip())
        return response.json() if response.content else {}

    # ---- orders -------------------------------------------------------------------------------------------------
    def fetch_orders(self, since: datetime | None) -> list[ExternalOrder]:
        created_after = (since or datetime(2026, 1, 1, tzinfo=UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        params: dict[str, Any] = {"MarketplaceIds": self._marketplace, "LastUpdatedAfter": created_after}
        out: list[ExternalOrder] = []
        while True:
            payload = self._request("GET", "/orders/v0/orders", params=params).get("payload", {})
            for order in payload.get("Orders", []):
                order_id = order["AmazonOrderId"]
                items = self._request("GET", f"/orders/v0/orders/{order_id}/orderItems").get("payload", {})
                lines = tuple(
                    ExternalLine(sku=i["SellerSKU"], quantity=Decimal(str(i.get("QuantityOrdered", 0))), title=i.get("Title"))
                    for i in items.get("OrderItems", []) if Decimal(str(i.get("QuantityOrdered", 0))) > 0
                )
                status = "cancelled" if order.get("OrderStatus") == "Canceled" else "open"
                if order.get("OrderStatus") == "Pending":
                    continue  # not yet confirmed by Amazon; it is picked up on a later sync
                out.append(ExternalOrder(order_id, datetime.fromisoformat(order["PurchaseDate"].replace("Z", "+00:00")), status, lines))
            token = payload.get("NextToken")
            if not token:
                return out
            params = {"MarketplaceIds": self._marketplace, "NextToken": token}

    # ---- stock --------------------------------------------------------------------------------------------------
    def push_quantity(self, sku: str, quantity: int, *, product_type: str | None) -> None:
        if not product_type:
            raise AdapterError(f"Set the Amazon product type on listing {sku} before pushing stock")
        body = {
            "productType": product_type,
            "patches": [{
                "op": "replace",
                "path": "/attributes/fulfillment_availability",
                "value": [{"fulfillment_channel_code": "DEFAULT", "quantity": max(0, int(quantity))}],
            }],
        }
        self._request("PATCH", f"/listings/2021-08-01/items/{quote(self._seller, safe='')}/{quote(sku, safe='')}",
                      params={"marketplaceIds": self._marketplace}, json=body)


def adapter_for(kind: str, mode: str, *, client: httpx.Client | None = None) -> Adapter:
    if mode == "live" and kind == "amazon":
        return AmazonAdapter(client)
    if mode == "live":
        raise AdapterError(f"Live mode is not available for {kind} yet")
    return DemoAdapter()
