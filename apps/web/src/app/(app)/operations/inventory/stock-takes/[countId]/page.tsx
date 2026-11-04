import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { StockTakeScreen } from "@/features/inventory/document-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-inventory-stock-take");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ countId: string }> }) {
  const { countId } = await params;
  if (!UUID_PATTERN.test(countId)) notFound();
  return <StockTakeScreen key={countId} countId={countId} />;
}
