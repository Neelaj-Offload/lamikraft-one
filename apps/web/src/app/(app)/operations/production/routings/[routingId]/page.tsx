import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { RoutingScreen } from "@/features/production/master-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-production-routing");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** A routing version with its operations. */
export default async function Page({ params }: { params: Promise<{ routingId: string }> }) {
  const { routingId } = await params;
  if (!UUID_PATTERN.test(routingId)) notFound();
  return <RoutingScreen key={routingId} routingId={routingId} />;
}
