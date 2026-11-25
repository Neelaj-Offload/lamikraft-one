"use client";

import type { CSSProperties } from "react";
import { useState } from "react";
import type { ShipmentSummary } from "@/features/logistics/api";
import { formatDecimal } from "@/lib/format/money";
import { useZone } from "@/lib/session/context";
import { packingStatus, shipmentStatus, useOrderSearch, type OrderOption } from "~/data/dispatch";
import { riseIndex } from "~/lib/motion";
import { Badge, ComboBox, Dash, DateText, SegmentedLinks } from "~/ui";

/** Small shared parts of the dispatch screens. */

/** Inline style for a staggered entrance: `<li className="rise-plain" style={stagger(i)}>`. */
export const stagger = (index: number) => riseIndex(index) as CSSProperties;

/** Shipments and packing lists are two lists of one area: a pill row switches between them. */
export function DispatchSwitch({ current }: { current: "shipments" | "packing-lists" }) {
  return (
    <SegmentedLinks
      label="Dispatch lists"
      value={current}
      options={[
        { value: "shipments", label: "Shipments", href: "/operations/dispatch" },
        { value: "packing-lists", label: "Packing lists", href: "/operations/dispatch/packing-lists" },
      ]}
    />
  );
}

export function ShipmentStatusBadge({ status, size }: { status: string; size?: "sm" }) {
  const look = shipmentStatus(status);
  return (
    <Badge tone={look.tone} dot size={size}>
      {look.label}
    </Badge>
  );
}

export function PackingStatusBadge({ status, size }: { status: string; size?: "sm" }) {
  const look = packingStatus(status);
  return (
    <Badge tone={look.tone} dot size={size}>
      {look.label}
    </Badge>
  );
}

/** A shipment still waiting to leave after its cutoff. */
export const pastCutoff = (shipment: Pick<ShipmentSummary, "is_past_cutoff" | "status">) =>
  shipment.is_past_cutoff && (shipment.status === "planned" || shipment.status === "booked");

/** The cutoff in the person's zone, flagged once it has passed while the goods are still here. */
export function Cutoff({ shipment, className }: { shipment: Pick<ShipmentSummary, "cutoff_at" | "is_past_cutoff" | "status">; className?: string }) {
  if (!shipment.cutoff_at) return <span className={`text-ink-3 ${className ?? ""}`}>No cutoff</span>;
  return (
    <span className={`flex flex-wrap items-center gap-2 ${className ?? ""}`}>
      <DateText value={shipment.cutoff_at} style="dayTime" />
      {pastCutoff(shipment) ? (
        <Badge tone="ember" size="sm" icon="alert">
          Past cutoff
        </Badge>
      ) : null}
    </span>
  );
}

/** A decimal string (CBM, kilograms) in the person's locale, exactly as the server sent it. */
export function Decimal({ value, unit, className }: { value: string | null | undefined; unit?: string; className?: string }) {
  const { locale } = useZone();
  const text = formatDecimal(value, { locale, maxFractionDigits: 6 });
  if (text === null) return <Dash className={className} />;
  return (
    <span className={`lk-tnum whitespace-nowrap ${className ?? ""}`}>
      {text}
      {unit ? ` ${unit}` : ""}
    </span>
  );
}

/** Confirmed or held sales orders, searched on the server by number or customer as the person types. */
export function OrderPicker({ value, onChange, error }: { value: OrderOption | null; onChange: (order: OrderOption | null) => void; error?: string }) {
  const [text, setText] = useState(value?.label ?? "");
  const { options, isSearching, emptyText } = useOrderSearch(text, value);
  return (
    <ComboBox
      label="Sales order"
      placeholder="Order number or customer"
      help="Only confirmed orders, and orders on hold, can be packed and shipped."
      items={options.map((order) => ({ id: order.id, label: order.label, description: order.description }))}
      inputValue={text}
      onInputChange={(next) => {
        setText(next);
        if (value && next !== value.label) onChange(null);
      }}
      selectedKey={value?.id ?? null}
      onSelectionChange={(id) => {
        const order = options.find((option) => option.id === id) ?? null;
        onChange(order);
        if (order) setText(order.label);
      }}
      isLoading={isSearching}
      emptyText={emptyText}
      isRequired
      error={error}
    />
  );
}
