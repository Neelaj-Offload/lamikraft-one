import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { StockDocument } from "~/screens/stock/document-record";
import { stockRecordViewFrom } from "~/screens/stock/labels";

export const metadata: Metadata = { title: "Stock adjustment · Operations" };

/** A stock adjustment: overview and lines (`?view=`). */
export default async function StockAdjustmentPage({
  params,
  searchParams,
}: {
  params: Promise<{ adjustmentId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { adjustmentId } = await params;
  if (!UUID_PATTERN.test(adjustmentId)) notFound();
  const view = stockRecordViewFrom((await searchParams).view);
  return <StockDocument key={adjustmentId} kind="adjustment" id={adjustmentId} view={view} />;
}
