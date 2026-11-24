import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { PurchaseOrderRecord } from "~/screens/purchasing/po-record";
import { poViewFrom } from "~/screens/purchasing/views";

export const metadata: Metadata = { title: "Purchase order · Operations" };

/** A purchase order: overview, lines, receipts and vendor bills (`?view=`). */
export default async function PurchaseOrderPage({
  params,
  searchParams,
}: {
  params: Promise<{ poId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { poId } = await params;
  if (!UUID_PATTERN.test(poId)) notFound();
  const view = poViewFrom((await searchParams).view);
  return <PurchaseOrderRecord key={poId} poId={poId} view={view} />;
}
