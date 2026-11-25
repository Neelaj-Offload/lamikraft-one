import type { Metadata } from "next";
import { partyListKey, partyListStateFrom } from "@/features/parties/list-state";
import { CustomerList } from "~/screens/sales/customers/list";
import { LeadList } from "~/screens/sales/leads/list";
import { leadListKey, leadListStateFrom } from "~/screens/sales/leads/list-state";

export const metadata: Metadata = { title: "Leads and customers" };

/** One URL; `?status=prospect` is the lead pipeline, `?status=active` is Customers, no status is everyone. */
export default async function CustomersPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const search = await searchParams;
  if ((Array.isArray(search.status) ? search.status[0] : search.status) === "prospect") {
    const state = leadListStateFrom(search);
    return <LeadList key={leadListKey(state)} state={state} />;
  }
  const state = partyListStateFrom(search);
  return <CustomerList key={partyListKey(state)} state={state} />;
}
