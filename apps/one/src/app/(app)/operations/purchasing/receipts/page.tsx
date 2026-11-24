import type { Metadata } from "next";
import { receiptStateFrom } from "@/features/procurement/list-state";
import { ReceiptList } from "~/screens/purchasing/receipt-list";

export const metadata: Metadata = { title: "Goods receipts · Operations" };

/** Goods receipts: "waiting for QC" and the page offset live in the URL. */
export default async function ReceiptsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = receiptStateFrom(await searchParams);
  return <ReceiptList state={state} />;
}
