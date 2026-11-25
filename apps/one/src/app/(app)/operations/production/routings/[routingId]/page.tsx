import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { RoutingRecord } from "~/screens/production/routing-record";

export const metadata: Metadata = { title: "Routing · Operations" };

/** A routing version: its operations, work centres and standard times. */
export default async function RoutingPage({ params }: { params: Promise<{ routingId: string }> }) {
  const { routingId } = await params;
  if (!UUID_PATTERN.test(routingId)) notFound();
  return <RoutingRecord key={routingId} routingId={routingId} />;
}
