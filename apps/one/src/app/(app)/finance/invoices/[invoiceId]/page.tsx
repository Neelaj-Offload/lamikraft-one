import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { DocumentRecord } from "~/screens/finance/document-record";
import { documentViewFrom } from "~/screens/finance/views";

export const metadata: Metadata = { title: "Invoice · Finance" };

/** An invoice: overview, lines, settlements, activity (`?view=`). */
export default async function InvoicePage({
  params,
  searchParams,
}: {
  params: Promise<{ invoiceId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { invoiceId } = await params;
  if (!UUID_PATTERN.test(invoiceId)) notFound();
  const view = documentViewFrom((await searchParams).view);
  return <DocumentRecord key={invoiceId} kind="invoice" id={invoiceId} view={view} />;
}
