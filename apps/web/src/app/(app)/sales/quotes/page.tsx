import type { Metadata } from "next";
import { quoteListStateFrom } from "@/features/sales/list-state";
import { QuoteList } from "@/features/sales/quote-list";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-quotes");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** Quotes: search, status and scope filters and the page offset all live in the URL. */
export default async function QuotesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = quoteListStateFrom(await searchParams);
  return <QuoteList key={`${state.q}|${state.status}|${state.scope}|${state.offset}`} state={state} />;
}
