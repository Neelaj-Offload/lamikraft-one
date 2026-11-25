import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { ShipmentRecord } from "~/screens/dispatch/shipment-record";
import { shipmentViewFrom } from "~/screens/dispatch/views";

export const metadata: Metadata = { title: "Shipment · Operations" };

/** A shipment: overview, challan and packing list, tracking (`?view=`). */
export default async function ShipmentPage({
  params,
  searchParams,
}: {
  params: Promise<{ shipmentId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { shipmentId } = await params;
  if (!UUID_PATTERN.test(shipmentId)) notFound();
  const view = shipmentViewFrom((await searchParams).view);
  return <ShipmentRecord key={shipmentId} shipmentId={shipmentId} view={view} />;
}
