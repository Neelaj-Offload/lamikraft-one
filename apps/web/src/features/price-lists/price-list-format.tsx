"use client";

import { StatusPill, type Tone } from "@/components/ui/badge";
import { productsMessages as m } from "@/messages/products";
import type { PartyMini, PriceScope } from "./types";

export const PRICE_LIST_TONE: Record<string, Tone> = { draft: "neutral", active: "success", retired: "neutral" };
export const PRICE_LIST_ITEM_TONE: Record<string, Tone> = { active: "success", retired: "neutral" };

export function PriceListStatusPill({ status }: { status: string }) {
  return <StatusPill tone={PRICE_LIST_TONE[status] ?? "neutral"}>{m.priceLists.status[status] ?? status}</StatusPill>;
}

/** "Customer · Acme GmbH", "Customer type · Dealer" or "Standard". */
export function scopeText(scope: PriceScope | string, party: PartyMini | null, customerType: string | null): string {
  const label = m.priceLists.scopes[scope] ?? scope;
  if (scope === "customer" && party) return `${label} · ${party.display_name}`;
  if (scope === "customer_type" && customerType) return `${label} · ${m.priceLists.customerTypes[customerType] ?? customerType}`;
  return label;
}
