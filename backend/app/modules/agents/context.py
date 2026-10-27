"""Screen-context grounding and ordinal resolution (ai-routing.md section 4.1).

The client's context is a hint. Every referenced record is re-read through the owning module's source reader
(``app.platform.sources``), which applies that resource's policy; unknown types and invisible records are dropped
silently (no existence leak) and only the visible references become ``agents_object_context`` rows.
"""

from __future__ import annotations

import importlib
import importlib.util
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.agents.schemas import ScreenContext
from app.platform import sources
from app.platform.sources import SourceFacts
from app.platform.uow import UnitOfWork

#: output field names -> resource types, for typed object-context rows from tool outputs
FIELD_RESOURCE_TYPES: dict[str, str] = {
    "party_id": "parties.party",
    "product_id": "catalogue.product",
    "price_list_id": "pricing.price_list",
    "item_id": "pricing.price_list_item",
    "price_list_item_id": "pricing.price_list_item",
    "quote_id": "sales.quote",
    "line_id": "sales.quote_line",
    "enquiry_id": "sales.enquiry",
    "message_id": "sales.customer_message",
    "origin_message_id": "sales.customer_message",
}
BRIEFINGS_SERVICE = "app.modules.briefings.service"


@dataclass(frozen=True)
class ContextRef:
    resource_type: str
    resource_id: uuid.UUID
    origin: str  # screen | tool | card
    version: int | None = None
    ref_key: str | None = None
    list_key: str | None = None
    ordinal: int | None = None
    label: str | None = None
    path: str | None = None
    role: str | None = None
    stale: bool = False  # the client's version differs from the re-read record


def _reread(uow: UnitOfWork, resource_type: str, resource_id: uuid.UUID) -> SourceFacts | None:
    if not sources.has_reader(resource_type):
        return None
    return sources.read(uow, resource_type, resource_id)


def ground_screen_context(uow: UnitOfWork, context: ScreenContext | None) -> list[ContextRef]:
    """Visible, re-read references of the screen context (focus, records, visible items)."""
    if context is None:
        return []
    refs: list[ContextRef] = []
    seen: set[tuple[str, uuid.UUID, str | None]] = set()
    candidates: list[tuple[str, uuid.UUID, int | None, str | None, str | None, int | None, str | None]] = []
    if context.focus is not None:
        candidates.append((context.focus.type, context.focus.id, context.focus.version, None, None, None, "focus"))
    for record in context.records:
        candidates.append((record.type, record.id, record.version, None, None, None, record.role or "record"))
    for item in context.visible_items:
        candidates.append((item.type, item.id, item.version, item.ref, item.list_key, item.ordinal, "visible"))
    for resource_type, resource_id, version, ref_key, list_key, ordinal, role in candidates:
        key = (resource_type, resource_id, ref_key)
        if key in seen:
            continue
        seen.add(key)
        facts = _reread(uow, resource_type, resource_id)
        if facts is None:
            continue  # unknown type or not visible to this actor: dropped without revealing existence
        refs.append(ContextRef(
            resource_type=resource_type, resource_id=resource_id, origin="screen", version=facts.version,
            ref_key=ref_key, list_key=list_key, ordinal=ordinal, label=facts.label, path=facts.canonical_path,
            role=role, stale=version is not None and facts.version is not None and version != facts.version,
        ))
    return refs


def typed_refs_from_output(output: Any, *, origin: str = "tool") -> list[ContextRef]:
    """Object-context rows for the typed ids a tool output carries (``party_id`` -> parties.party ...)."""
    refs: dict[tuple[str, uuid.UUID], ContextRef] = {}
    stack: list[Any] = [output]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                resource_type = FIELD_RESOURCE_TYPES.get(str(key))
                if resource_type and isinstance(value, (str, uuid.UUID)):
                    try:
                        rid = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
                    except ValueError:
                        continue
                    refs.setdefault((resource_type, rid), ContextRef(
                        resource_type=resource_type, resource_id=rid, origin=origin,
                        label=str(current.get("display_name") or current.get("quote_number") or current.get("product_key") or "") or None,
                    ))
                else:
                    stack.append(value)
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
    return list(refs.values())


def refs_from_cards(cards: Sequence[Mapping[str, Any]]) -> list[ContextRef]:
    """Object context carried by the previous assistant turn's cards (origin ``card``)."""
    refs: list[ContextRef] = []
    for card in cards:
        for ref in typed_refs_from_output(card, origin="card"):
            refs.append(ref)
        kind = card.get("kind")
        if kind == "record_link" and card.get("resource_id") and card.get("resource_type"):
            refs.append(ContextRef(
                resource_type=str(card["resource_type"]), resource_id=uuid.UUID(str(card["resource_id"])),
                origin="card", label=card.get("label"), path=card.get("path"), ordinal=card.get("ordinal"),
            ))
    return refs


# ---- ordinals ("open the second item") -----------------------------------------------------------------------
@dataclass(frozen=True)
class OrdinalResolution:
    status: str  # resolved | stale | none
    ref: ContextRef | None = None
    list_key: str | None = None
    size: int = 0


def _briefing_pin_resolver() -> Any | None:
    """Seam: ``briefings.service.resolve_pin(uow, pin_id, ordinal)`` when the briefings module is installed."""
    if importlib.util.find_spec(BRIEFINGS_SERVICE) is None:
        return None
    module = importlib.import_module(BRIEFINGS_SERVICE)
    return getattr(module, "resolve_pin", None)


def resolve_ordinal(
    uow: UnitOfWork, context: ScreenContext | None, refs: Sequence[ContextRef], ordinal: int,
    last_list: Sequence[Mapping[str, Any]] = (),
) -> OrdinalResolution:
    """Resolve "the Nth item": active briefing pin first, then the visible list on screen, then the last list the
    assistant presented. A list that changed since the user saw it yields ``stale`` (clarify, never guess)."""
    if context is not None and context.briefing_pin is not None:
        resolver = _briefing_pin_resolver()
        if resolver is not None:
            pinned = resolver(uow, context.briefing_pin.pin_id, ordinal)
            if pinned is not None:
                return OrdinalResolution(status="resolved", ref=ContextRef(
                    resource_type=str(getattr(pinned, "resource_type", "")), resource_id=pinned.resource_id,
                    origin="screen", label=getattr(pinned, "label", None), path=getattr(pinned, "path", None), ordinal=ordinal,
                ), list_key="briefing_pin")
    visible = [r for r in refs if r.origin == "screen" and r.ordinal is not None]
    if visible:
        list_key = visible[0].list_key
        if context is not None and context.selection:
            selected = {r.ref_key for r in visible} & set(context.selection)
            if selected:
                list_key = next(r.list_key for r in visible if r.ref_key in selected)
        items = [r for r in visible if r.list_key == list_key]
        size = len([i for i in (context.visible_items if context else []) if i.list_key == list_key])
        target = ordinal if ordinal > 0 else size
        match = next((r for r in items if r.ordinal == target), None)
        if match is None:
            return OrdinalResolution(status="none", list_key=list_key, size=size)
        if match.stale:
            return OrdinalResolution(status="stale", ref=match, list_key=list_key, size=size)
        return OrdinalResolution(status="resolved", ref=match, list_key=list_key, size=size)
    if last_list:
        target = ordinal if ordinal > 0 else len(last_list)
        if 1 <= target <= len(last_list):
            item = last_list[target - 1]
            rid = item.get("resource_id") or (item.get("action") or {}).get("value")
            try:
                resource_id = uuid.UUID(str(rid))
            except (ValueError, TypeError):
                return OrdinalResolution(status="none", list_key="last_presented", size=len(last_list))
            return OrdinalResolution(status="resolved", ref=ContextRef(
                resource_type=str(item.get("resource_type") or FIELD_RESOURCE_TYPES.get(f"{(item.get('action') or {}).get('slot')}_id", "unknown.record")),
                resource_id=resource_id, origin="card", label=item.get("label"), path=item.get("path"), ordinal=target,
            ), list_key="last_presented", size=len(last_list))
        return OrdinalResolution(status="none", list_key="last_presented", size=len(last_list))
    return OrdinalResolution(status="none")
