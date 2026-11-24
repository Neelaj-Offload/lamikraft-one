import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { ReceiptRecord } from "~/screens/purchasing/receipt-record";
import { receiptViewFrom } from "~/screens/purchasing/views";

export const metadata: Metadata = { title: "Goods receipt · Operations" };

/** A goods receipt: overview and lines (`?view=`). */
export default async function ReceiptPage({
  params,
  searchParams,
}: {
  params: Promise<{ grnId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { grnId } = await params;
  if (!UUID_PATTERN.test(grnId)) notFound();
  const view = receiptViewFrom((await searchParams).view);
  return <ReceiptRecord key={grnId} grnId={grnId} view={view} />;
}
