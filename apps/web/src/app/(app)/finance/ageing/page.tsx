import type { Metadata } from "next";
import { AgeingScreen } from "@/features/finance/finance-screens";
import { ageingDateFrom } from "@/features/finance/list-state";
import { getRoute } from "@/lib/routes";

const route = getRoute("finance-ageing");

export const metadata: Metadata = { title: `${route.label} · Finance` };

export default async function AgeingPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <AgeingScreen asOf={ageingDateFrom(await searchParams)} />;
}
