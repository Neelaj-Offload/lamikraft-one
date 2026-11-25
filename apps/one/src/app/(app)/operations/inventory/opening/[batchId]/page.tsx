import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { StockDocument } from "~/screens/stock/document-record";
import { stockRecordViewFrom } from "~/screens/stock/labels";

export const metadata: Metadata = { title: "Opening stock · Operations" };

/** An opening stock batch: overview and lines (`?view=`). */
export default async function OpeningStockPage({
  params,
  searchParams,
}: {
  params: Promise<{ batchId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { batchId } = await params;
  if (!UUID_PATTERN.test(batchId)) notFound();
  const view = stockRecordViewFrom((await searchParams).view);
  return <StockDocument key={batchId} kind="opening_batch" id={batchId} view={view} />;
}
