import type { Metadata } from "next";
import { shipmentStateFrom } from "@/features/logistics/list-state";
import { ShipmentList } from "~/screens/dispatch/shipment-list";

export const metadata: Metadata = { title: "Dispatch · Operations" };

/** The dispatch board: shipments by cutoff; search, status and the page offset live in the URL. */
export default async function DispatchPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = shipmentStateFrom(await searchParams);
  return <ShipmentList key={`${state.q}|${state.status}|${state.offset}`} state={state} />;
}
