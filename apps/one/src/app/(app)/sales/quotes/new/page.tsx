import type { Metadata } from "next";
import { UUID_PATTERN } from "@/lib/app-links";
import { QuotationNew } from "~/screens/sales/quotations/quotation-new";

export const metadata: Metadata = { title: "New quotation · Sales" };

/** Start a quotation; `?enquiry=<id>` starts it from an enquiry (customer prefilled, enquiry linked). */
export default async function NewQuotationPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const raw = (await searchParams).enquiry;
  const enquiry = typeof raw === "string" && UUID_PATTERN.test(raw) ? raw : null;
  return <QuotationNew key={enquiry ?? "new"} enquiryId={enquiry} />;
}
