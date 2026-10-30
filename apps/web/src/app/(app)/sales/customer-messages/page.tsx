import type { Metadata } from "next";
import { CustomerMessageList } from "@/features/sales/customer-messages";
import { messageListStateFrom } from "@/features/sales/list-state";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-customer-messages");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** Customer messages with "Mark replied"; the status filter and page offset live in the URL. */
export default async function CustomerMessagesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = messageListStateFrom(await searchParams);
  return <CustomerMessageList key={`${state.status}|${state.offset}`} state={state} />;
}
