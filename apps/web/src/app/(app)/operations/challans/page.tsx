import type { Metadata } from "next";
import { ChallansPage, type ChallansSearchParams } from "@/features/challans/challans-page";
import { getRoute } from "@/lib/routes";

const route = getRoute("operations-challans");

export const metadata: Metadata = { title: `${route.label} · Operations` };

/** Delivery challans: search, status, type, destination, date, pending-return and scope filters and the page offset live in the URL. */
export default function OperationsChallansPage({ searchParams }: { searchParams: ChallansSearchParams }) {
  return <ChallansPage searchParams={searchParams} />;
}
