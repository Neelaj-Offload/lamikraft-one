import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PurchaseOrderScreen } from "@/features/procurement/po-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-purchasing-order");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ poId: string }> }) {
  const { poId } = await params;
  if (!UUID_PATTERN.test(poId)) notFound();
  return <PurchaseOrderScreen key={poId} poId={poId} />;
}
