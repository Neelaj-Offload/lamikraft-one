import type { Metadata } from "next";
import { receiptStateFrom } from "@/features/finance/list-state";
import { ReceiptList } from "~/screens/finance/receipt-list";

export const metadata: Metadata = { title: "Receipts · Finance" };

/** Receipts: search, the unallocated switch and the page offset live in the URL. */
export default async function ReceiptsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = receiptStateFrom(await searchParams);
  return <ReceiptList key={`${state.q}|${state.unallocated}|${state.offset}`} state={state} />;
}
