import type { Metadata } from "next";
import { ReceiptWorkspace } from "@/features/finance/receipt-workspace";
import { getRoute } from "@/lib/routes";

const route = getRoute("finance-receipt");

export const metadata: Metadata = { title: `${route.label} · Finance` };

export default async function ReceiptPage({ params }: { params: Promise<{ receiptId: string }> }) {
  const { receiptId } = await params;
  return <ReceiptWorkspace receiptId={receiptId} />;
}
