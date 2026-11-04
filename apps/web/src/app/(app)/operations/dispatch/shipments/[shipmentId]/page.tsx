import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ShipmentScreen } from "@/features/logistics/shipment-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-dispatch-shipment");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ shipmentId: string }> }) {
  const { shipmentId } = await params;
  if (!UUID_PATTERN.test(shipmentId)) notFound();
  return <ShipmentScreen key={shipmentId} shipmentId={shipmentId} />;
}
