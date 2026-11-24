import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { StockDocument } from "~/screens/stock/document-record";
import { stockRecordViewFrom } from "~/screens/stock/labels";

export const metadata: Metadata = { title: "Stock transfer · Operations" };

/** A stock transfer: overview and lines (`?view=`). */
export default async function StockTransferPage({
  params,
  searchParams,
}: {
  params: Promise<{ transferId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { transferId } = await params;
  if (!UUID_PATTERN.test(transferId)) notFound();
  const view = stockRecordViewFrom((await searchParams).view);
  return <StockDocument key={transferId} kind="transfer" id={transferId} view={view} />;
}
