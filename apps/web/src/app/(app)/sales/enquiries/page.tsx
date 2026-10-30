import type { Metadata } from "next";
import { EnquiryList, enquiryListStateFrom } from "@/features/sales/enquiries";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-enquiries");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** Enquiries: search, status and page offset live in the URL. */
export default async function EnquiriesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = enquiryListStateFrom(await searchParams);
  return <EnquiryList key={`${state.q}|${state.status}|${state.offset}`} state={state} />;
}
