import type { Metadata } from "next";
import { ageingDateFrom } from "@/features/finance/list-state";
import { Ageing } from "~/screens/finance/ageing";

export const metadata: Metadata = { title: "Ageing · Finance" };

/** Receivables ageing as of a date (`?as_of=YYYY-MM-DD`, today in company time when absent). */
export default async function AgeingPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <Ageing asOf={ageingDateFrom(await searchParams)} />;
}
