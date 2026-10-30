import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { QuoteWorkspace } from "@/features/sales/quote-workspace";
import { UUID_PATTERN } from "@/lib/app-links";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-quote");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** The quote workspace: terms, lines, server totals, allowed commands, revisions and history. */
export default async function QuotePage({ params }: { params: Promise<{ quoteId: string }> }) {
  const { quoteId } = await params;
  if (!UUID_PATTERN.test(quoteId)) notFound();
  return <QuoteWorkspace key={quoteId} quoteId={quoteId} />;
}
