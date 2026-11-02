import type { Metadata } from "next";
import { PartiesPage, type PartiesSearchParams } from "@/features/parties/parties-page";
import { getRoute } from "@/lib/routes";

const route = getRoute("sales-parties");

export const metadata: Metadata = { title: `${route.label} · Sales` };

/** Customers: search, role, status, type and archived filters and the page offset all live in the URL. */
export default function SalesPartiesPage({ searchParams }: { searchParams: PartiesSearchParams }) {
  return <PartiesPage searchParams={searchParams} />;
}
