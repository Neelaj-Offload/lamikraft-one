import type { Metadata } from "next";
import { partyListKey, partyListStateFrom } from "@/features/parties/list-state";
import { CustomerList } from "~/screens/sales/customers/list";

export const metadata: Metadata = { title: "Leads and customers" };

/** One list; `?status=prospect` is Leads, `?status=active` is Customers. */
export default async function CustomersPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = partyListStateFrom(await searchParams);
  return <CustomerList key={partyListKey(state)} state={state} />;
}
