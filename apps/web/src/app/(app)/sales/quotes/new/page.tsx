import type { Metadata } from "next";
import { QuoteCreate } from "@/features/sales/quote-create";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-quote-new");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** New quote; `?enquiry=<id>` starts it from an enquiry (customer prefilled, enquiry linked). */
export default async function NewQuotePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const raw = (await searchParams).enquiry;
  const enquiry = typeof raw === "string" && UUID_PATTERN.test(raw) ? raw : null;
  return <QuoteCreate key={enquiry ?? "new"} enquiryId={enquiry} />;
}
