import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { ReceiptRecord } from "~/screens/finance/receipt-record";
import { receiptViewFrom } from "~/screens/finance/views";

export const metadata: Metadata = { title: "Receipt · Finance" };

/** A receipt: overview with the allocation form, and its allocations (`?view=`). */
export default async function ReceiptPage({
  params,
  searchParams,
}: {
  params: Promise<{ receiptId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { receiptId } = await params;
  if (!UUID_PATTERN.test(receiptId)) notFound();
  const view = receiptViewFrom((await searchParams).view);
  return <ReceiptRecord key={receiptId} receiptId={receiptId} view={view} />;
}
