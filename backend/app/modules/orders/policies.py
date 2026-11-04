"""Sales order record scope (permissions.md §7.7): own/team/branch/company on ``owner_user_id`` and ``branch_id``
(sales own, operations branch, management and finance company). Lines and history are children authorised only
through their order. Reserving stock for an order needs ``inventory.stock.reserve`` in scope over the **order**
(sales own orders, operations branch), checked with :data:`ORDER_RESERVE_POLICY`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.orders.enums import OrderStatus
from app.modules.orders.models import SalesOrder, SalesOrderLine, SalesOrderStatusHistory
from app.platform.authz.context import ActorContext
from app.platform.authz.policy import Decision, ParentRef, ResourcePolicy

OPEN = frozenset({OrderStatus.DRAFT.value, OrderStatus.CONFIRMED.value, OrderStatus.ON_HOLD.value})


def order_rules(_ctx: ActorContext, o: Any) -> Mapping[str, Decision]:
    is_open = o.status in OPEN
    return {
        "update": Decision(is_open, None if is_open else "order_closed"),
        "transition": Decision(is_open, None if is_open else "order_closed"),
    }


ORDER_POLICY = ResourcePolicy(
    resource_type="orders.sales_order",
    model=SalesOrder,
    permission_prefix="orders.sales_order",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    business_key_column="order_number",
    label=lambda o: f"{o.order_number} · {o.party_name}",
    canonical_path=lambda o: f"/sales/orders/{o.id}",
    rules=order_rules,
    archived_column=None,
)
ORDER_LINE_POLICY = ResourcePolicy(
    resource_type="orders.sales_order_line",
    model=SalesOrderLine,
    permission_prefix="orders.sales_order",
    parent=ParentRef("orders.sales_order", "order_id"),
    archived_column=None,
)
ORDER_HISTORY_POLICY = ResourcePolicy(
    resource_type="orders.sales_order_status_history",
    model=SalesOrderStatusHistory,
    permission_prefix="orders.sales_order",
    parent=ParentRef("orders.sales_order", "order_id"),
    archived_column=None,
)
#: not registered (one policy per model): evaluates ``inventory.stock.reserve`` over the order's owner and branch
ORDER_RESERVE_POLICY = ResourcePolicy(
    resource_type="orders.sales_order[reserve]",
    model=SalesOrder,
    permission_prefix="inventory.stock",
    owner_columns=("owner_user_id",),
    branch_column="branch_id",
    archived_column=None,
)

POLICIES = [ORDER_POLICY, ORDER_LINE_POLICY, ORDER_HISTORY_POLICY]
