import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { ProformaRecord } from "~/screens/sales/proforma/record";

export const metadata: Metadata = { title: "Proforma invoice" };

export default async function ProformaInvoicePage({ params }: { params: Promise<{ proformaId: string }> }) {
  const { proformaId } = await params;
  if (!UUID_PATTERN.test(proformaId)) notFound();
  return <ProformaRecord key={proformaId} proformaId={proformaId} />;
}
