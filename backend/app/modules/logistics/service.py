"""Logistics public service (routers, jobs and other modules call this): packing lists (``packing_lists``), shipments,
container profiles and load suggestions (``shipments``), and the pure arithmetic (``packing``, ``load_planner``)."""

from __future__ import annotations

from app.modules.logistics import load_planner, packing, packing_lists, shipments

create_packing_list = packing_lists.create_packing_list
get_packing_list = packing_lists.get_packing_list
finalise_packing_list = packing_lists.finalise
refresh_packing_list = packing_lists.refresh
create_shipment = shipments.create_shipment
get_shipment = shipments.get_shipment
transition_shipment = shipments.transition
cutoff_instant = shipments.cutoff_instant
suggest_load = shipments.suggest_load
compute_line = packing.compute_line
plan_loads = load_planner.plan

__all__ = [
    "compute_line",
    "create_packing_list",
    "create_shipment",
    "cutoff_instant",
    "finalise_packing_list",
    "get_packing_list",
    "get_shipment",
    "plan_loads",
    "refresh_packing_list",
    "suggest_load",
    "transition_shipment",
]
