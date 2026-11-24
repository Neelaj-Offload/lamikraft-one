import type { Metadata } from "next";
import { enquiryListStateFrom } from "@/features/sales/list-state";
import { EnquiryList } from "~/screens/sales/enquiries/list";

export const metadata: Metadata = { title: "Enquiries" };

/** The enquiry pipeline; `?status=` picks a stage, `?q=` searches. */
export default async function EnquiriesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = enquiryListStateFrom(await searchParams);
  return <EnquiryList key={`${state.q}|${state.status ?? ""}|${state.offset}`} state={state} />;
}
