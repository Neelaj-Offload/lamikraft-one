"use client";

import { StatusPill, type Tone } from "@/components/ui/badge";
import { Quantity } from "@/components/ui/format";
import { challansMessages as m } from "@/messages/challans";
import type { QuantityByUnit } from "./types";

export const CHALLAN_STATUS_TONE: Record<string, Tone> = { draft: "neutral", issued: "info", closed: "success", cancelled: "neutral" };

export function ChallanStatusPill({ status }: { status: string }) {
  return <StatusPill tone={CHALLAN_STATUS_TONE[status] ?? "neutral"}>{m.status[status] ?? status}</StatusPill>;
}

/** Totals per unit from the server (`12 sheets · 2 pcs`); different units are never added together. */
export function QuantityList({ value, empty = "—" }: { value: QuantityByUnit; empty?: string }) {
  const entries = Object.entries(value);
  if (entries.length === 0) return <span className="text-ink-muted">{empty}</span>;
  return (
    <span className="inline-flex flex-wrap gap-x-2">
      {entries.map(([unit, quantity], index) => (
        <span key={unit} className="inline-flex items-center gap-2">
          {index > 0 ? <span aria-hidden="true">·</span> : null}
          <Quantity value={{ value: quantity, uom: unit }} />
        </span>
      ))}
    </span>
  );
}

export const OPERATIONS_NAV_LEADING = [{ id: "operations", label: m.overview, href: "/operations" }] as const;
