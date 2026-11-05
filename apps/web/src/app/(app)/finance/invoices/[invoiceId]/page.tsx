import type { Metadata } from "next";
import { DocWorkspace } from "@/features/finance/doc-workspace";
import { getRoute } from "@/lib/routes";

const route = getRoute("finance-invoice");

export const metadata: Metadata = { title: `${route.label} · Finance` };

export default async function InvoicePage({ params }: { params: Promise<{ invoiceId: string }> }) {
  const { invoiceId } = await params;
  return <DocWorkspace kind="invoice" id={invoiceId} />;
}
