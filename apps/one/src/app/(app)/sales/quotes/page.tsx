import type { Metadata } from "next";
import { quoteListStateFrom } from "@/features/sales/list-state";
import { QuotationList } from "~/screens/sales/quotations/quotation-list";

export const metadata: Metadata = { title: "Quotations · Sales" };

/** Quotations: search, status, scope and the page offset all live in the URL. */
export default async function QuotationsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = quoteListStateFrom(await searchParams);
  return <QuotationList key={`${state.q}|${state.status}|${state.scope}|${state.offset}`} state={state} />;
}
