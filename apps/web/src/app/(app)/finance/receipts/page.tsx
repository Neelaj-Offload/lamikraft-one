import type { Metadata } from "next";
import { ReceiptList } from "@/features/finance/finance-screens";
import { receiptStateFrom } from "@/features/finance/list-state";
import { getRoute } from "@/lib/routes";

const route = getRoute("finance-receipts");

export const metadata: Metadata = { title: `${route.label} · Finance` };

export default async function ReceiptsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <ReceiptList state={receiptStateFrom(await searchParams)} />;
}
