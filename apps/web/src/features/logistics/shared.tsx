"use client";

import { useQuery } from "@tanstack/react-query";
import { Link as RacLink } from "react-aria-components";
import { StatusPill, type Tone } from "@/components/ui/badge";
import { ComboBox } from "@/components/ui/select";
import { linkClasses } from "@/components/ui/styles";
import { fetchOrders } from "@/features/orders/api";
import { queryKeys } from "@/lib/api/query-keys";
import { formatDecimal } from "@/lib/format/money";
import { useDebouncedValue } from "@/lib/hooks";
import { useZone } from "@/lib/session/context";
import { logisticsMessages as m } from "@/messages/logistics";

const SHIPMENT_TONES: Record<string, Tone> = {
  planned: "neutral",
  booked: "info",
  dispatched: "info",
  in_transit: "info",
  delivered: "success",
  exception: "danger",
  cancelled: "neutral",
};
const PACKING_TONES: Record<string, Tone> = { draft: "neutral", final: "success", cancelled: "neutral" };

export function ShipmentStatusPill({ status }: { status: string }) {
  return <StatusPill tone={SHIPMENT_TONES[status] ?? "neutral"}>{m.shipmentStatus[status] ?? status}</StatusPill>;
}

export function PackingStatusPill({ status }: { status: string }) {
  return <StatusPill tone={PACKING_TONES[status] ?? "neutral"}>{m.packingStatus[status] ?? status}</StatusPill>;
}

/** The dispatch sub-navigation (shipments, packing lists). */
export function DispatchTabs({ current }: { current: "shipments" | "packing-lists" }) {
  const tabs = [
    { id: "shipments", href: "/operations/dispatch", label: m.tabs.shipments },
    { id: "packing-lists", href: "/operations/dispatch/packing-lists", label: m.tabs.packingLists },
  ] as const;
  return (
    <nav aria-label={m.tabs.label} className="flex flex-wrap gap-4 text-sm">
      {tabs.map((t) => (
        <RacLink key={t.id} href={t.href} aria-current={t.id === current ? "page" : undefined} className={`${linkClasses} ${t.id === current ? "font-semibold" : ""}`}>
          {t.label}
        </RacLink>
      ))}
    </nav>
  );
}

export interface OrderOption {
  id: string;
  label: string;
  detail?: string;
}

/** Sales orders the person can read, searched on the server by number or customer as they type. */
export function OrderPicker({ text, onText, value, onChange }: { text: string; onText: (text: string) => void; value: OrderOption | null; onChange: (order: OrderOption | null) => void }) {
  const p = m.orderPicker;
  const q = useDebouncedValue(text.trim(), 250);
  const search = useQuery({
    queryKey: queryKeys.orders.list({ q, picker: true }),
    queryFn: ({ signal }) => fetchOrders({ q }, signal),
    enabled: q.length >= 2,
    staleTime: 30_000,
  });
  const found = (search.data?.items ?? [])
    .filter((o) => o.status === "confirmed" || o.status === "on_hold")
    .map((o) => ({ id: o.id, label: o.order_number, detail: o.party.display_name }));
  const options = [...(value ? [value] : []), ...found.filter((o) => o.id !== value?.id)];
  return (
    <ComboBox
      label={p.label}
      placeholder={p.hint}
      emptyText={q.length < 2 ? p.hint : search.isError ? p.failed : p.none}
      options={options}
      value={value?.id ?? null}
      inputValue={text}
      onInputChange={onText}
      onChange={(id) => {
        const order = options.find((o) => o.id === id) ?? null;
        onChange(order);
        if (order) onText(order.label);
      }}
    />
  );
}

/** A DecimalStr (CBM, kilograms) in the person's locale, as sent by the server (no float conversion). */
export function DecimalText({ value }: { value: string }) {
  const { locale } = useZone();
  return <span className="tabular">{formatDecimal(value, { locale, maxFractionDigits: 6 }) ?? value}</span>;
}
