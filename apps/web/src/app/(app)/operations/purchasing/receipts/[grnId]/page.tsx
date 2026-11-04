import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ReceiptScreen } from "@/features/procurement/receipt-screens";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-purchasing-receipt");

export const metadata: Metadata = { title: `${route.label} · Operations` };

export default async function Page({ params }: { params: Promise<{ grnId: string }> }) {
  const { grnId } = await params;
  if (!UUID_PATTERN.test(grnId)) notFound();
  return <ReceiptScreen key={grnId} grnId={grnId} />;
}
