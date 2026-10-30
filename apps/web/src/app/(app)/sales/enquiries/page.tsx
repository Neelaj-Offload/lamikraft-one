import type { Metadata } from "next";
import { EnquiryList } from "@/features/sales/enquiries";
import { enquiryListStateFrom } from "@/features/sales/list-state";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-enquiries");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** Enquiries: search, status and page offset live in the URL. */
export default async function EnquiriesPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const state = enquiryListStateFrom(await searchParams);
  return <EnquiryList key={`${state.q}|${state.status}|${state.offset}`} state={state} />;
}
