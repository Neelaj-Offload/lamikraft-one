import type { Metadata } from "next";
import { shipmentStateFrom } from "@/features/logistics/list-state";
import { ShipmentsScreen } from "@/features/logistics/shipment-screens";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-dispatch");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** The dispatch board: shipments ordered by cutoff; search and status live in the URL. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = shipmentStateFrom(await searchParams);
  return <ShipmentsScreen state={state} />;
}
