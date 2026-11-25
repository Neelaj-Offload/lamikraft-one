import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { UUID_PATTERN } from "@/lib/app-links";
import { QuotationRecord } from "~/screens/sales/quotations/quotation-record";
import { quotationViewFrom } from "~/screens/sales/quotations/views";

export const metadata: Metadata = { title: "Quotation · Sales" };

/** A quotation: overview, lines, terms, documents and revisions, activity (`?view=`). */
export default async function QuotationPage({
  params,
  searchParams,
}: {
  params: Promise<{ quoteId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { quoteId } = await params;
  if (!UUID_PATTERN.test(quoteId)) notFound();
  const view = quotationViewFrom((await searchParams).view);
  return <QuotationRecord key={quoteId} quoteId={quoteId} view={view} />;
}
