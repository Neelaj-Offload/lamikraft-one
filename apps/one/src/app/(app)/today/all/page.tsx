import type { Metadata } from "next";
import { AllItemsScreen } from "~/screens/today/all-screen";
import { allFilterFrom, type AllSearchParams } from "~/screens/today/all-state";

export const metadata: Metadata = { title: "All of today · Today" };

/** `?group=<section|snoozed>&kind=<rule family>`: the filters live in the URL. */
export default async function TodayAllPage({ searchParams }: { searchParams: Promise<AllSearchParams> }) {
  const filter = allFilterFrom(await searchParams);
  return <AllItemsScreen filter={filter} />;
}
